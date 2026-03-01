#!/usr/bin/env python3
"""Quick verifier for Azure Document Translation configuration.

Run after exporting your Azure env vars to confirm the app can instantiate
the AzureDocumentTranslator and access Blob containers as configured.
"""
import os
import sys

from importlib import import_module

def main():
    print("Checking Azure environment variables...")
    required = [
        "AZURE_DOCUMENT_TRANSLATION_ENDPOINT",
        "AZURE_DOCUMENT_TRANSLATION_KEY",
        "AZURE_BLOB_CONN_STR",
        "AZURE_BLOB_INPUT_CONTAINER",
        "AZURE_BLOB_OUTPUT_CONTAINER",
    ]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print("Missing env vars:", ", ".join(missing))
        print("Set them and re-run. Example:\nexport AZURE_DOCUMENT_TRANSLATION_ENDPOINT=...\nexport AZURE_DOCUMENT_TRANSLATION_KEY=...\nexport AZURE_BLOB_CONN_STR=...\nexport AZURE_BLOB_INPUT_CONTAINER=...\nexport AZURE_BLOB_OUTPUT_CONTAINER=...")
        sys.exit(2)

    try:
        mod = import_module('app.translator')
        AzureDoc = getattr(mod, 'AzureDocumentTranslator')
    except Exception as e:
        print('Unable to import AzureDocumentTranslator from app.translator:', e)
        sys.exit(2)

    try:
        print('Instantiating AzureDocumentTranslator (this will validate credentials)...')
        t = AzureDoc()
        print('✓ Successfully instantiated AzureDocumentTranslator')
    except Exception as e:
        print('ERROR: Failed to instantiate AzureDocumentTranslator:')
        print(e)
        sys.exit(1)

    print('Basic check passed. To fully verify, ensure the input/output containers exist and are reachable.')

if __name__ == '__main__':
    main()
