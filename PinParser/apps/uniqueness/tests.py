from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from apps.uniqueness.models import ModelProvider, UniquenessConfig
from apps.uniqueness.services.ai_uniqueness_service import AIUniquenessService


@override_settings(
    OMNIROUTE_API_KEY='test-route-key',
    OMNIROUTE_BASE_URL='http://localhost:20128/v1',
    OMNIROUTE_MODEL='kr/claude-sonnet-4.5',
)
class OmniRouteTests(SimpleTestCase):
    @patch('apps.uniqueness.services.ai_uniqueness_service.OpenAI')
    def test_omniroute_request_uses_environment_settings(self, client):
        config = UniquenessConfig(model_provider=ModelProvider.OMNIROUTE)
        config.full_clean()
        client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"New","description":"Text"}'))]
        )
        service = AIUniquenessService(SimpleNamespace(id=1), config)
        self.assertIn('"title"', service._call_api('Rewrite this pin', 1))
        client.assert_called_once_with(api_key='test-route-key', base_url='http://localhost:20128/v1')
        client.return_value.chat.completions.create.assert_called_once_with(
            model='kr/claude-sonnet-4.5',
            messages=[{'role': 'user', 'content': 'Rewrite this pin'}],
            temperature=1.0, max_tokens=500,
        )

    @override_settings(OMNIROUTE_API_KEY='')
    def test_omniroute_requires_environment_key(self):
        with self.assertRaises(ValidationError):
            UniquenessConfig(model_provider=ModelProvider.OMNIROUTE).clean()

    @patch('apps.uniqueness.services.ai_uniqueness_service.OpenAI')
    def test_omniroute_request_uses_configured_model(self, client):
        config = UniquenessConfig(
            model_provider=ModelProvider.OMNIROUTE,
            omniroute_model='  custom/model  ',
        )
        config.full_clean()
        client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))]
        )
        service = AIUniquenessService(SimpleNamespace(id=1), config)
        service._call_api('Rewrite this pin', 1)
        self.assertEqual(
            client.return_value.chat.completions.create.call_args.kwargs['model'],
            'custom/model',
        )

    def test_whitespace_model_falls_back_to_environment(self):
        config = UniquenessConfig(model_provider=ModelProvider.OMNIROUTE, omniroute_model='   ')
        self.assertEqual(config.model, 'kr/claude-sonnet-4.5')

    def test_existing_providers_keep_their_keys_and_models(self):
        for provider, model in [(ModelProvider.OPENAI, 'gpt-4.1-nano-2025-04-14'),
                                (ModelProvider.DASHSCOPE, 'qwen3.7-flash')]:
            with self.subTest(provider=provider):
                config = UniquenessConfig(model_provider=provider, openai_api_key='existing-key',
                                          omniroute_model='custom/model')
                config.full_clean()
                self.assertEqual(config.api_key, 'existing-key')
                self.assertEqual(config.model, model)
                config.openai_api_key = ''
                with self.assertRaises(ValidationError):
                    config.clean()
