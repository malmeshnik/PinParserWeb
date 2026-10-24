from types import SimpleNamespace
from unittest.mock import patch

import httpx2
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from openai import AuthenticationError, BadRequestError, NotFoundError, PermissionDeniedError

from apps.uniqueness.admin import UniquenessConfigForm
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


def _api_error(error_cls, status_code, param=None):
    response = httpx2.Response(status_code, request=httpx2.Request('POST', 'https://api.openai.com/v1'))
    return error_cls('error', response=response, body={'param': param})


def _completion(content='{"title":"New","description":"Text"}', finish_reason='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason=finish_reason,
    )])


@patch('apps.uniqueness.services.ai_uniqueness_service.OpenAI')
class OpenAIModelTests(SimpleTestCase):
    def _service(self, **config_kwargs):
        config = UniquenessConfig(model_provider=ModelProvider.OPENAI, openai_api_key='key', **config_kwargs)
        config.full_clean()
        return AIUniquenessService(SimpleNamespace(id=1), config)

    def test_default_model_is_unchanged(self, client):
        service = self._service()
        client.return_value.chat.completions.create.return_value = _completion()
        service._call_api('Rewrite', 1)
        client.return_value.chat.completions.create.assert_called_once_with(
            model='gpt-4.1-nano-2025-04-14',
            messages=[{'role': 'user', 'content': 'Rewrite'}],
            temperature=1.0, max_completion_tokens=500,
        )

    def test_configured_model_is_used(self, client):
        service = self._service(openai_model=' gpt-4.1-mini ')
        client.return_value.chat.completions.create.return_value = _completion()
        service._call_api('Rewrite', 1)
        self.assertEqual(client.return_value.chat.completions.create.call_args.kwargs['model'], 'gpt-4.1-mini')

    def test_blank_model_falls_back_to_default(self, client):
        self.assertEqual(self._service(openai_model='  ').config.model, 'gpt-4.1-nano-2025-04-14')

    def test_reasoning_model_params(self, client):
        service = self._service(openai_model='gpt-5-mini', temperature=0.7)
        client.return_value.chat.completions.create.return_value = _completion()
        service._call_api('Rewrite', 1)
        kwargs = client.return_value.chat.completions.create.call_args.kwargs
        self.assertNotIn('temperature', kwargs)
        self.assertEqual(kwargs['reasoning_effort'], 'low')
        self.assertEqual(kwargs['max_completion_tokens'], 2500)

    def test_rejected_params_are_adapted_and_remembered(self, client):
        service = self._service(openai_model='custom-model', temperature=0.7)
        create = client.return_value.chat.completions.create
        create.side_effect = [
            _api_error(BadRequestError, 400, 'temperature'),
            _api_error(BadRequestError, 400, 'max_completion_tokens'),
            _completion(),
            _completion(),
        ]
        self.assertIn('"title"', service._call_api('Rewrite', 1))
        self.assertEqual(service.request_params, {'max_tokens': 500})
        service._call_api('Rewrite', 2)
        self.assertEqual(create.call_args.kwargs, {
            'model': 'custom-model',
            'messages': [{'role': 'user', 'content': 'Rewrite'}],
            'max_tokens': 500,
        })
        self.assertEqual(create.call_count, 4)

    def test_other_bad_request_is_not_retried(self, client):
        service = self._service()
        client.return_value.chat.completions.create.side_effect = _api_error(BadRequestError, 400, 'messages')
        self.assertEqual(service._call_api('Rewrite', 1), '')
        self.assertEqual(client.return_value.chat.completions.create.call_count, 1)
        self.assertIsNone(service.fatal_error)

    def test_unavailable_model_aborts_processing(self, client):
        for error in (_api_error(NotFoundError, 404), _api_error(PermissionDeniedError, 403),
                      _api_error(AuthenticationError, 401)):
            with self.subTest(error=type(error).__name__):
                service = self._service(openai_model='gpt-missing')
                client.return_value.chat.completions.create.side_effect = error
                self.assertEqual(service._call_api('Rewrite', 1), '')
                self.assertTrue(service.fatal_error)
                self.assertTrue(service.stop_event.is_set())

    def test_empty_content_is_handled(self, client):
        service = self._service(openai_model='gpt-5-nano')
        client.return_value.chat.completions.create.return_value = _completion(content=None, finish_reason='length')
        self.assertEqual(service._call_api('Rewrite', 1), '')


@patch('apps.uniqueness.admin.OpenAI')
class UniquenessConfigFormTests(SimpleTestCase):
    def _form(self, **data):
        data = {
            'name': 'Config', 'is_active': True, 'model_provider': ModelProvider.OPENAI,
            'openai_model': 'gpt-4.1-mini', 'omniroute_model': '', 'openai_api_key': 'key',
            'max_tokens_title': 100, 'max_tokens_description': 400, 'temperature': 1.0,
            'prompt_template': 'Rewrite {{title}}', 'max_requests_per_minute': 450, 'max_workers': 5,
            **data,
        }
        return UniquenessConfigForm(data=data)

    def test_existing_model_is_accepted(self, client):
        self.assertTrue(self._form().is_valid())
        client.return_value.models.retrieve.assert_called_once_with('gpt-4.1-mini')

    def test_unknown_model_is_rejected(self, client):
        client.return_value.models.retrieve.side_effect = _api_error(NotFoundError, 404)
        form = self._form(openai_model='gpt-typo')
        self.assertFalse(form.is_valid())
        self.assertIn('openai_model', form.errors)

    def test_network_error_does_not_block_saving(self, client):
        client.return_value.models.retrieve.side_effect = ConnectionError('offline')
        self.assertTrue(self._form().is_valid())

    def test_other_providers_are_not_checked(self, client):
        with override_settings(OMNIROUTE_API_KEY='route-key'):
            self.assertTrue(self._form(model_provider=ModelProvider.OMNIROUTE, openai_api_key='').is_valid())
        client.assert_not_called()
