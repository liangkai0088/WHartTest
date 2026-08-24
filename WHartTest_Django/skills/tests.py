import io
import os
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from projects.models import Project
from skills.models import Skill


class TestcaseRuntimeScreenshotTests(TestCase):
    def test_collect_runtime_skill_screenshots_filters_by_chat_session(self):
        from django.test.utils import override_settings
        from testcases.tasks import _collect_runtime_skill_screenshots

        with tempfile.TemporaryDirectory() as temp_media_root:
            screenshots_dir = os.path.join(
                temp_media_root,
                'skill_runtime',
                'screenshots',
                '37',
                '61',
            )
            os.makedirs(screenshots_dir)
            with open(os.path.join(screenshots_dir, '.chat_session'), 'w', encoding='utf-8') as f:
                f.write('current-session')
            with open(os.path.join(screenshots_dir, 'step1.png'), 'wb') as f:
                f.write(b'png')

            with override_settings(MEDIA_ROOT=temp_media_root, MEDIA_URL='/media/'):
                screenshots = _collect_runtime_skill_screenshots(37, 61, 'current-session')
                stale_screenshots = _collect_runtime_skill_screenshots(37, 61, 'old-session')

        self.assertEqual(screenshots, ['/media/skill_runtime/screenshots/37/61/step1.png'])
        self.assertEqual(stale_screenshots, [])


class SkillZipUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='skill_tester', password='secret')
        self.project = Project.objects.create(
            name='skill-upload-project',
            description='test project',
            creator=self.user,
        )

    def _build_zip_file(self, file_map: dict[str, str], name: str = 'skill.zip') -> SimpleUploadedFile:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path, content in file_map.items():
                zf.writestr(path, content)
        buffer.seek(0)
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='application/zip')

    def test_create_from_zip_supports_deeply_nested_skill_root(self):
        zip_file = self._build_zip_file({
            'repo-main/packages/agent/demo-skill/SKILL.md': """---
name: nested-skill
description: nested zip skill
---

# Nested Skill
""",
            'repo-main/packages/agent/demo-skill/scripts/run.py': "print('ok')\n",
        })

        with tempfile.TemporaryDirectory() as temp_media_root:
            with self.settings(MEDIA_ROOT=temp_media_root):
                skills = Skill.create_from_zip(zip_file=zip_file, project=self.project, creator=self.user)
                self.assertEqual(len(skills), 1)
                skill = skills[0]

                self.assertEqual(skill.name, 'nested-skill')
                self.assertIn('nested zip skill', skill.description)
                self.assertTrue(os.path.exists(os.path.join(skill.get_full_path(), 'scripts', 'run.py')))

    def test_create_from_zip_supports_multiple_skills_in_one_archive(self):
        zip_file = self._build_zip_file({
            'bundle/skill-a/SKILL.md': """---
name: skill-a
description: skill a
---
""",
            'bundle/skill-a/run.py': "print('a')\n",
            'bundle/skill-b/SKILL.md': """---
name: skill-b
description: skill b
---
""",
            'bundle/skill-b/lib/main.py': "print('b')\n",
        })

        with tempfile.TemporaryDirectory() as temp_media_root:
            with self.settings(MEDIA_ROOT=temp_media_root):
                skills = Skill.create_from_zip(zip_file=zip_file, project=self.project, creator=self.user)

                self.assertEqual(len(skills), 2)
                self.assertEqual({skill.name for skill in skills}, {'skill-a', 'skill-b'})
                self.assertTrue(any(os.path.exists(os.path.join(skill.get_full_path(), 'run.py')) for skill in skills))
                self.assertTrue(any(os.path.exists(os.path.join(skill.get_full_path(), 'lib', 'main.py')) for skill in skills))


class InitBundledSkillsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='secret',
        )
        self.project = Project.objects.create(
            name='bundled-skill-project',
            description='test project',
            creator=self.user,
        )

    def test_init_skills_syncs_nested_bundled_skill_directory(self):
        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as temp_media_root, tempfile.TemporaryDirectory() as skills_dir:
            nested_skill_dir = os.path.join(skills_dir, 'draw-skill', 'drawio')
            os.makedirs(nested_skill_dir)
            with open(os.path.join(nested_skill_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
                f.write('''---\nname: drawio\ndescription: drawio skill\n---\n\n# Drawio\n''')
            with open(os.path.join(nested_skill_dir, 'README.md'), 'w', encoding='utf-8') as f:
                f.write('docs')

            with self.settings(MEDIA_ROOT=temp_media_root):
                call_command('init_skills', skills_dir=skills_dir, verbosity=0)

                skill = Skill.objects.get(name='drawio')
                self.assertTrue(os.path.exists(os.path.join(skill.get_full_path(), 'SKILL.md')))
                self.assertTrue(os.path.exists(os.path.join(skill.get_full_path(), 'README.md')))


class SkillRuntimeRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='runtime_admin',
            email='runtime_admin@example.com',
            password='secret',
        )
        self.project = Project.objects.create(
            name='runtime-skill-project',
            description='test project',
            creator=self.user,
        )

    def test_execute_skill_recovers_missing_directory_from_bundled_skills(self):
        from orchestrator_integration.builtin_tools.skill_tools import get_skill_tools

        with tempfile.TemporaryDirectory() as temp_media_root, tempfile.TemporaryDirectory() as skills_dir:
            bundled_skill_dir = os.path.join(skills_dir, 'demo-skill')
            os.makedirs(bundled_skill_dir)
            with open(os.path.join(bundled_skill_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
                f.write('''---\nname: demo-skill\ndescription: demo skill\n---\n\n# Demo\n''')

            with self.settings(MEDIA_ROOT=temp_media_root):
                skill = Skill.objects.create(
                    project=self.project,
                    creator=self.user,
                    name='demo-skill',
                    description='old',
                    skill_content='',
                    skill_path=f'skills/{self.project.id}/999',
                    is_active=True,
                )
                self.assertFalse(os.path.exists(skill.get_full_path()))

                tools = get_skill_tools(user_id=self.user.id, project_id=self.project.id)
                read_tool = next(tool for tool in tools if tool.name == 'read_skill_content')

                with patch.dict(os.environ, {'BUNDLED_SKILLS_DIR': skills_dir}):
                    content = read_tool.invoke({'skill_name': 'demo-skill'})

                skill.refresh_from_db()
                self.assertIn('# Demo', content)
                self.assertTrue(os.path.exists(os.path.join(skill.get_full_path(), 'SKILL.md')))
