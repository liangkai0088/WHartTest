from django.db import migrations, models
import django.db.models.deletion
import uuid
import knowledge.models


class Migration(migrations.Migration):

    dependencies = [
        ('knowledge', '0017_remove_document_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentImage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('image_file', models.ImageField(upload_to=knowledge.models.document_image_upload_path, verbose_name='图片文件')),
                ('image_index', models.PositiveIntegerField(help_text='对应 {{IMAGE:N}} 占位符，从 0 开始', verbose_name='图片索引')),
                ('page_number', models.PositiveIntegerField(blank=True, null=True, verbose_name='页码')),
                ('content_type', models.CharField(default='image/png', max_length=100, verbose_name='MIME类型')),
                ('width', models.IntegerField(blank=True, null=True, verbose_name='宽度')),
                ('height', models.IntegerField(blank=True, null=True, verbose_name='高度')),
                ('file_size', models.IntegerField(default=0, verbose_name='文件大小')),
                ('ocr_text', models.TextField(blank=True, null=True, verbose_name='OCR文本')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='knowledge.document', verbose_name='所属文档')),
            ],
            options={
                'verbose_name': '文档图片',
                'verbose_name_plural': '文档图片',
                'ordering': ['document', 'image_index'],
                'indexes': [
                    models.Index(fields=['document', 'image_index'], name='knowledge_docimage_doc_idx'),
                ],
            },
        ),
    ]
