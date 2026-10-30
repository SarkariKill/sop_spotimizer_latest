"""Regression checks for the Azure-only LLM gateway."""
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from services.llm import main


class AzureOnlyProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_only_azure_is_advertised(self):
        self.assertEqual(set(self.client.get('/providers').json()['providers']), {'azure_openai'})
        self.assertEqual(self.client.get('/health').json()['provider'], 'azure_openai')

    def test_removed_provider_is_rejected_before_dispatch(self):
        with patch.object(main.AZURE_PROVIDER, 'generate', new_callable=AsyncMock) as generate:
            response = self.client.post('/generate', json={
                'provider': 'unsupported_provider', 'model': 'test', 'api_key': 'test',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            })
        self.assertEqual(response.status_code, 422)
        generate.assert_not_awaited()

    def test_default_requests_dispatch_to_azure(self):
        with patch.object(main.AZURE_PROVIDER, 'generate', new_callable=AsyncMock, return_value='OK') as generate:
            response = self.client.post('/generate', json={
                'model': 'deployment', 'api_key': 'test',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'azure_openai')
        self.assertEqual(response.json()['content'], 'OK')
        generate.assert_awaited_once()
