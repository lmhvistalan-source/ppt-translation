import os
import time
import uuid
import tempfile
from pathlib import Path
from typing import List

import requests

from azure.core.credentials import AzureKeyCredential
from azure.ai.translation.document import DocumentTranslationClient, DocumentTranslationInput, TranslationTarget
from azure.storage.blob import BlobServiceClient, generate_container_sas, ContainerSasPermissions


AZURE_TEXT_ENDPOINT = os.getenv("AZURE_TRANSLATOR_ENDPOINT")
AZURE_TEXT_KEY = os.getenv("AZURE_TRANSLATOR_KEY")
AZURE_TEXT_REGION = os.getenv("AZURE_TRANSLATOR_REGION")

# For document translation (preserve Office formatting) we expect these env vars
AZ_DOC_ENDPOINT = os.getenv("AZURE_DOCUMENT_TRANSLATION_ENDPOINT")
AZ_DOC_KEY = os.getenv("AZURE_DOCUMENT_TRANSLATION_KEY")
AZ_BLOB_CONN_STR = os.getenv("AZURE_BLOB_CONN_STR")
AZ_INPUT_CONTAINER = os.getenv("AZURE_BLOB_INPUT_CONTAINER")
AZ_OUTPUT_CONTAINER = os.getenv("AZURE_BLOB_OUTPUT_CONTAINER")


class TranslatorBase:
    def translate_texts(self, texts: List[str], target: str) -> List[str]:
        raise NotImplementedError()

    def translate_file(self, input_path: str, target: str) -> str:
        """Translate a file and return path to translated file. Optional to implement."""
        raise NotImplementedError()


class MockTranslator(TranslatorBase):
    def translate_texts(self, texts: List[str], target: str) -> List[str]:
        return [f"[{target}] {t}" if t else "" for t in texts]

    def translate_file(self, input_path: str, target: str) -> str:
        # Mock: just copy file with language prefix
        import shutil
        out_path = Path(input_path).parent / (Path(input_path).stem + f"_translated_{target}{Path(input_path).suffix}")
        shutil.copy(input_path, out_path)
        return str(out_path)


class AzureTextTranslator(TranslatorBase):
    def __init__(self):
        if not AZURE_TEXT_ENDPOINT or not AZURE_TEXT_KEY:
            raise RuntimeError("AZURE_TRANSLATOR_ENDPOINT and AZURE_TRANSLATOR_KEY must be set")
        self.endpoint = AZURE_TEXT_ENDPOINT.rstrip("/")
        self.key = AZURE_TEXT_KEY
        self.region = AZURE_TEXT_REGION

    def translate_texts(self, texts: List[str], target: str) -> List[str]:
        # Skip translation if target is English (assume source is also English)
        if target.lower() == "en":
            return texts
        
        url = f"{self.endpoint}/translate?api-version=3.0&to={target}"
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"}
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region

        body = [{"Text": t} for t in texts]
        results = []
        batch_size = 50
        for i in range(0, len(body), batch_size):
            chunk = body[i:i+batch_size]
            resp = requests.post(url, headers=headers, json=chunk)
            resp.raise_for_status()
            data = resp.json()
            for item in data:
                if item and "translations" in item and len(item["translations"]) > 0:
                    results.append(item["translations"][0]["text"])
                else:
                    results.append("")
        return results


class HuggingFaceTranslator(TranslatorBase):
    """Uses Hugging Face Transformers (Helsinki-NLP/Opus-MT models) for fully local translation.
    No external API calls, no data collection. Downloads model once and caches locally.
    Good for privacy-sensitive internal use.
    """

    def __init__(self):
        from transformers import pipeline
        self.pipeline = pipeline
        self.translators = {}  # Cache per language pair

    def _get_translator(self, target: str):
        """Lazy-load translation pipeline for a target language."""
        if target not in self.translators:
            # Opus-MT models use language codes like 'en' but sometimes need adapting
            model_name = f"Helsinki-NLP/Opus-MT-en-{target}"
            try:
                print(f"Loading translation model: {model_name}")
                self.translators[target] = self.pipeline("translation_en_to_" + target, model=model_name)
            except Exception as e:
                print(f"Warning: Model {model_name} not found, trying fallback")
                # Fallback: try the auto pipeline
                try:
                    self.translators[target] = self.pipeline("translation", model=model_name)
                except Exception as e2:
                    raise RuntimeError(f"Could not load translation model for {target}: {e2}")
        return self.translators[target]

    def translate_texts(self, texts: List[str], target: str) -> List[str]:
        """Translate a list of texts using HF Transformers."""
        # Skip translation if target is English (assume source is also English)
        if target.lower() == "en":
            return texts
        
        translator = self._get_translator(target)
        results = []
        for text in texts:
            if not text or text.strip() == "":
                results.append(text)
            else:
                try:
                    result = translator(text, max_length=512)
                    # Result is a list with dict containing 'translation_text'
                    translated = result[0].get("translation_text", text) if result else text
                    results.append(translated)
                except Exception as e:
                    print(f"Warning: translation failed for '{text}': {e}")
                    results.append(text)  # fallback: return original
        return results

    def translate_file(self, input_path: str, target: str) -> str:
        """Translate a file using text-based translation."""
        import shutil
        out_path = Path(input_path).parent / (Path(input_path).stem + f"_translated_{target}{Path(input_path).suffix}")
        
        if Path(input_path).suffix.lower() == ".pptx":
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            prs = Presentation(str(input_path))
            runs = []
            texts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    # Handle regular text shapes
                    if hasattr(shape, "text_frame"):
                        for paragraph in shape.text_frame.paragraphs:
                            for run in paragraph.runs:
                                runs.append(run)
                                texts.append(run.text or "")
                    # Handle tables
                    if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                        table = shape.table
                        for row in table.rows:
                            for cell in row.cells:
                                for paragraph in cell.text_frame.paragraphs:
                                    for run in paragraph.runs:
                                        runs.append(run)
                                        texts.append(run.text or "")
            translations = self.translate_texts(texts, target)
            for run, t in zip(runs, translations):
                run.text = t
            prs.save(str(out_path))
        elif Path(input_path).suffix.lower() == ".docx":
            from docx import Document
            doc = Document(str(input_path))
            runs = []
            texts = []
            for para in doc.paragraphs:
                for run in para.runs:
                    runs.append(run)
                    texts.append(run.text or "")
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            for run in para.runs:
                                runs.append(run)
                                texts.append(run.text or "")
            translations = self.translate_texts(texts, target)
            for run, t in zip(runs, translations):
                run.text = t
            doc.save(str(out_path))
        else:
            shutil.copy(input_path, out_path)
        return str(out_path)


class GoogleTranslator(TranslatorBase):
    """Uses googletrans (Google Translate) for free, no-auth translation.
    Good for quick testing and internal use.
    Note: googletrans may be rate-limited by Google for high-volume usage.
    """

    def __init__(self):
        from googletrans import Translator
        self.translator = Translator()

    def translate_texts(self, texts: List[str], target: str) -> List[str]:
        """Translate a list of texts using Google Translate."""
        # Skip translation if target is English (assume source is also English)
        if target.lower() == "en":
            return texts
        
        results = []
        for text in texts:
            if not text or text.strip() == "":
                results.append(text)
            else:
                try:
                    result = self.translator.translate(text, target)
                    # googletrans returns an object with .text attribute
                    results.append(result.text if hasattr(result, 'text') else str(result))
                except Exception as e:
                    print(f"Warning: translation failed for '{text}': {e}")
                    results.append(text)  # fallback: return original
        return results

    def translate_file(self, input_path: str, target: str) -> str:
        """Translate a file using text-based translation (no document-level support)."""
        import shutil
        out_path = Path(input_path).parent / (Path(input_path).stem + f"_translated_{target}{Path(input_path).suffix}")
        
        if Path(input_path).suffix.lower() == ".pptx":
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            prs = Presentation(str(input_path))
            runs = []
            texts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    # Handle regular text shapes
                    if hasattr(shape, "text_frame"):
                        for paragraph in shape.text_frame.paragraphs:
                            for run in paragraph.runs:
                                runs.append(run)
                                texts.append(run.text or "")
                    # Handle tables
                    if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                        table = shape.table
                        for row in table.rows:
                            for cell in row.cells:
                                for paragraph in cell.text_frame.paragraphs:
                                    for run in paragraph.runs:
                                        runs.append(run)
                                        texts.append(run.text or "")
            translations = self.translate_texts(texts, target)
            for run, t in zip(runs, translations):
                run.text = t
            prs.save(str(out_path))
        elif Path(input_path).suffix.lower() == ".docx":
            from docx import Document
            doc = Document(str(input_path))
            runs = []
            texts = []
            for para in doc.paragraphs:
                for run in para.runs:
                    runs.append(run)
                    texts.append(run.text or "")
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            for run in para.runs:
                                runs.append(run)
                                texts.append(run.text or "")
            translations = self.translate_texts(texts, target)
            for run, t in zip(runs, translations):
                run.text = t
            doc.save(str(out_path))
        else:
            shutil.copy(input_path, out_path)
        return str(out_path)


class AzureDocumentTranslator(TranslatorBase):
    """Uses Azure Document Translation to translate whole Office documents while preserving formatting.

    Requires the following env vars:
    - AZURE_DOCUMENT_TRANSLATION_ENDPOINT
    - AZURE_DOCUMENT_TRANSLATION_KEY
    - AZURE_BLOB_CONN_STR
    - AZURE_BLOB_INPUT_CONTAINER
    - AZURE_BLOB_OUTPUT_CONTAINER
    """

    def __init__(self):
        if not all([AZ_DOC_ENDPOINT, AZ_DOC_KEY, AZ_BLOB_CONN_STR, AZ_INPUT_CONTAINER, AZ_OUTPUT_CONTAINER]):
            raise RuntimeError("AZURE_DOCUMENT_TRANSLATION_*, AZURE_BLOB_CONN_STR, and container names must be set")
        self.endpoint = AZ_DOC_ENDPOINT.rstrip("/")
        self.key = AZ_DOC_KEY
        self.blob_service = BlobServiceClient.from_connection_string(AZ_BLOB_CONN_STR)
        self.input_container = AZ_INPUT_CONTAINER
        self.output_container = AZ_OUTPUT_CONTAINER
        self.client = DocumentTranslationClient(self.endpoint, AzureKeyCredential(self.key))

    def _generate_container_sas(self, container_name: str, permission: ContainerSasPermissions, expiry_hours: int = 2) -> str:
        account_name = self.blob_service.account_name
        from azure.storage.blob import generate_container_sas
        from datetime import datetime, timedelta

        sas = generate_container_sas(
            account_name=account_name,
            container_name=container_name,
            account_key=self.blob_service.credential.account_key if hasattr(self.blob_service.credential, 'account_key') else None,
            permission=permission,
            expiry=datetime.utcnow() + timedelta(hours=expiry_hours),
        )
        return sas

    def translate_file(self, input_path: str, target: str) -> str:
        # upload input file to input container
        blob_name = f"upload-{uuid.uuid4().hex}-{Path(input_path).name}"
        container_client = self.blob_service.get_container_client(self.input_container)
        with open(input_path, "rb") as f:
            container_client.upload_blob(name=blob_name, data=f, overwrite=True)

        # generate SAS urls for input and output containers
        from azure.storage.blob import ContainerSasPermissions
        from datetime import datetime, timedelta
        account_name = self.blob_service.account_name
        # Generate SAS tokens using connection string's account key
        # If account key not available, user must pre-create SAS-enabled containers
        try:
            sas_input = generate_container_sas(account_name, self.input_container, account_key=self.blob_service.credential.account_key, permission=ContainerSasPermissions(read=True, list=True), expiry=datetime.utcnow()+timedelta(hours=2))
            sas_output = generate_container_sas(account_name, self.output_container, account_key=self.blob_service.credential.account_key, permission=ContainerSasPermissions(write=True, list=True), expiry=datetime.utcnow()+timedelta(hours=2))
        except Exception:
            raise RuntimeError("Unable to generate container SAS. Ensure connection string uses account key and is valid.")

        input_sas_url = f"https://{account_name}.blob.core.windows.net/{self.input_container}?{sas_input}"
        output_sas_url = f"https://{account_name}.blob.core.windows.net/{self.output_container}?{sas_output}"

        # create translation input
        source = DocumentTranslationInput(source_url=input_sas_url, targets=[TranslationTarget(language=target, storage_url=output_sas_url)])
        poller = self.client.begin_translation(inputs=[source])
        result = poller.result()

        # find translated document in output container
        out_container = self.blob_service.get_container_client(self.output_container)
        # translation output may place files under subfolders; attempt to find by original filename suffix
        basename = Path(input_path).name
        candidate = None
        for blob in out_container.list_blobs():
            if blob.name.endswith(basename) and blob.name != blob_name:
                candidate = blob.name
                break
        if not candidate:
            # fallback: pick first blob
            blobs = list(out_container.list_blobs())
            if not blobs:
                raise RuntimeError("No translated file found in output container")
            candidate = blobs[0].name

        # download the translated blob to a temp file
        out_path = Path(tempfile.mkdtemp()) / Path(candidate).name
        with open(out_path, "wb") as f:
            data = out_container.download_blob(candidate)
            f.write(data.readall())

        # cleanup: delete uploaded blob and optionally the translated blob from container
        try:
            container_client.delete_blob(blob_name)
        except Exception:
            pass

        try:
            out_container.delete_blob(candidate)
        except Exception:
            pass

        return str(out_path)

    def translate_texts(self, texts: List[str], target: str) -> List[str]:
        # Not optimized: fall back to text translator per-item using Text API
        if not AZURE_TEXT_ENDPOINT or not AZURE_TEXT_KEY:
            return [f"[{target}] {t}" if t else "" for t in texts]
        azure_text = AzureTextTranslator()
        return azure_text.translate_texts(texts, target)


def get_translator():
    provider = os.getenv("TRANSLATOR_PROVIDER", "google").lower()
    if provider == "azure_doc":
        return AzureDocumentTranslator()
    if provider == "azure":
        return AzureTextTranslator()
    if provider == "google":
        return GoogleTranslator()
    if provider == "huggingface":
        return HuggingFaceTranslator()
    return GoogleTranslator()  # Default to Google Translate instead of Mock
