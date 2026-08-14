from unittest.mock import Mock, patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import KnowledgeGlobalConfig
from .views import _mask_secret


class KnowledgeGlobalConfigSecretHandlingTests(TestCase):
    """验证全局配置中的脱敏密钥不会在保存或测试时被破坏。"""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass123",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_authenticate(user=self.admin)
        self.config = KnowledgeGlobalConfig.get_config()
        self.config.embedding_service = "custom"
        self.config.api_base_url = "https://integrate.api.nvidia.com/v1/embeddings"
        self.config.api_key = "nvapi-real-secret-NvRS"
        self.config.model_name = "baai/bge-m3"
        self.config.reranker_service = "custom"
        self.config.reranker_api_url = "https://reranker.example.com/v1/rerank"
        self.config.reranker_api_key = "reranker-real-secret"
        self.config.reranker_model_name = "Qwen3-VL-Reranker-2B"
        self.config.save()

    def test_put_global_config_keeps_real_secret_when_api_key_is_omitted(self):
        payload = {
            "embedding_service": "custom",
            "api_base_url": "https://integrate.api.nvidia.com/v1/embeddings",
            "model_name": "baai/bge-m3",
            "reranker_service": "custom",
            "reranker_api_url": "https://reranker.example.com/v1/rerank",
            "reranker_model_name": "Qwen3-VL-Reranker-2B",
            "chunk_size": 1200,
            "chunk_overlap": 150,
        }

        update_response = self.client.put(
            "/api/knowledge/global-config/", payload, format="json"
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.config.refresh_from_db()
        self.assertEqual(self.config.api_key, "nvapi-real-secret-NvRS")
        self.assertEqual(self.config.reranker_api_key, "reranker-real-secret")
        self.assertEqual(self.config.chunk_size, 1200)
        self.assertEqual(self.config.chunk_overlap, 150)

    @patch("requests.Session.post")
    def test_embedding_connection_uses_stored_secret_when_api_key_is_omitted(
        self, mock_post
    ):
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}]
        }
        mock_post.return_value = mock_response

        response = self.client.post(
            "/api/knowledge/test-embedding-connection/",
            {
                "embedding_service": "custom",
                "api_base_url": "https://integrate.api.nvidia.com/v1/embeddings",
                "model_name": "baai/bge-m3",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json().get("data", response.json())
        self.assertEqual(payload["success"], True)
        _, kwargs = mock_post.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer nvapi-real-secret-NvRS",
        )

    def test_put_global_config_keeps_real_secret_when_masked_value_is_sent_back(self):
        response = self.client.get("/api/knowledge/global-config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payload = response.json()
        payload["chunk_size"] = 1300
        payload["chunk_overlap"] = 160

        update_response = self.client.put(
            "/api/knowledge/global-config/", payload, format="json"
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.config.refresh_from_db()
        self.assertEqual(self.config.api_key, "nvapi-real-secret-NvRS")
        self.assertEqual(self.config.reranker_api_key, "reranker-real-secret")
        self.assertEqual(self.config.chunk_size, 1300)
        self.assertEqual(self.config.chunk_overlap, 160)


class DocumentImageResolveTests(TestCase):
    """验证检索结果中 {{IMAGE:N}} 占位符被解析为 resolved_images 元数据。"""

    def setUp(self):
        from .services import VectorStoreManager

        # 绕过 __init__（避免初始化 embedding/稀疏编码器）
        self.manager = object.__new__(VectorStoreManager)

    def test_resolve_images_fills_resolved_images(self):
        results = [
            {
                "content": "见 {{IMAGE:0}} 与 {{IMAGE:1}}",
                "metadata": {"document_id": "doc-1", "chunk_index": 0},
                "similarity_score": 0.9,
            },
            {
                "content": "无图片文本",
                "metadata": {"document_id": "doc-1", "chunk_index": 1},
                "similarity_score": 0.5,
            },
        ]
        mock_qs = MagicMock()
        mock_qs.values.return_value = [
            {"document_id": "doc-1", "image_index": 0},
            {"document_id": "doc-1", "image_index": 1},
        ]
        with patch(
            "knowledge.services.DocumentImage.objects.filter", return_value=mock_qs
        ):
            resolved = self.manager._resolve_images(results)

        self.assertEqual(len(resolved), 2)
        images = resolved[0]["metadata"]["resolved_images"]
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["image_index"], 0)
        self.assertIn(
            "/api/knowledge/documents/doc-1/images/0/", images[0]["image_url"]
        )
        # 无图片占位符的结果不应包含 resolved_images
        self.assertNotIn("resolved_images", resolved[1]["metadata"])

    def test_resolve_images_skips_when_no_placeholder(self):
        results = [
            {
                "content": "普通文本",
                "metadata": {"document_id": "doc-1"},
                "similarity_score": 0.8,
            }
        ]
        resolved = self.manager._resolve_images(results)
        self.assertNotIn("resolved_images", resolved[0]["metadata"])


class DocumentImageSaveTests(TestCase):
    """验证图片保存到 DocumentImage 的逻辑（mock 文件写入）。"""

    def test_save_image_returns_incrementing_index(self):
        from .models import Document
        from .services import DocumentProcessor

        document = MagicMock(spec=Document)
        document.id = "doc-test-id"
        document.images.count.return_value = 0

        with patch("knowledge.services.DocumentImage.objects.create") as mock_create:
            mock_img = MagicMock()
            mock_create.return_value = mock_img

            processor = DocumentProcessor()
            idx = processor._save_image(document, b"fake-image-bytes", page_number=2)

        self.assertEqual(idx, 0)
        mock_create.assert_called_once()
        # image_file.save 被调用（写入图片文件）
        mock_img.image_file.save.assert_called_once()
        self.assertEqual(mock_create.call_args.kwargs["page_number"], 2)
