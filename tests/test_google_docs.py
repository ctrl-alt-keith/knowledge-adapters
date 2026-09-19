"""Unit tests for Google Docs publishing."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest

from knowledge_adapters import google_docs as gdocs


@pytest.mark.parametrize("character", ["\x00", "\x08", "\x0c", "\x1f", "\ue000", "\uf8ff"])
def test_gdocs_publish_rejects_content_docs_would_strip(character: str) -> None:
    docs_service = Mock()
    drive_service = Mock()

    with pytest.raises(ValueError, match="cannot preserve unsupported character"):
        gdocs.publish_markdown(
            content=f"before{character}after",
            title="Example",
            folder_id="folder-123",
            docs_service=docs_service,
            drive_service=drive_service,
        )

    docs_service.documents.return_value.create.assert_not_called()
    docs_service.documents.return_value.batchUpdate.assert_not_called()
    drive_service.files.return_value.create.assert_not_called()


@pytest.mark.parametrize(
    ("title", "folder_id", "message"),
    [("   ", None, "title must not be blank"), ("Example", "  ", "folder_id must not be blank")],
)
def test_gdocs_publish_rejects_blank_destination_identifiers(
    title: str, folder_id: str | None, message: str
) -> None:
    docs_service = Mock()
    drive_service = Mock()

    with pytest.raises(ValueError, match=message):
        gdocs.publish_markdown(
            content="# Bundle\n",
            title=title,
            folder_id=folder_id,
            docs_service=docs_service,
            drive_service=drive_service,
        )

    docs_service.documents.return_value.create.assert_not_called()
    drive_service.files.return_value.create.assert_not_called()


def test_gdocs_publish_normalizes_title_and_folder_id_before_api_call() -> None:
    docs_service = Mock()
    drive_service = Mock()
    documents = docs_service.documents.return_value
    drive_service.files.return_value.create.return_value.execute.return_value = {"id": "doc-id"}

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="  Example  ",
        folder_id="  folder-123  ",
        docs_service=docs_service,
        drive_service=drive_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    drive_service.files.return_value.create.assert_called_once_with(
        body={
            "name": "Example",
            "mimeType": gdocs.GOOGLE_DOC_MIME_TYPE,
            "parents": ["folder-123"],
        },
        fields="id",
    )
    documents.batchUpdate.assert_called_once()


def test_gdocs_publish_uses_docs_api_service() -> None:
    docs_service = Mock()
    documents = docs_service.documents.return_value
    documents.create.return_value.execute.return_value = {"documentId": "doc-id"}

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="Example",
        docs_service=docs_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    documents.create.assert_called_once_with(body={"title": "Example"})
    documents.batchUpdate.assert_called_once_with(
        documentId="doc-id",
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": "# Bundle\n",
                    }
                }
            ]
        },
    )
    documents.batchUpdate.return_value.execute.assert_called_once_with()


def test_gdocs_publish_empty_content_skips_batch_update() -> None:
    docs_service = Mock()
    documents = docs_service.documents.return_value
    documents.create.return_value.execute.return_value = {"documentId": "doc-id"}

    url = gdocs.publish_markdown(
        content="",
        title="Example",
        docs_service=docs_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    documents.create.assert_called_once_with(body={"title": "Example"})
    documents.batchUpdate.assert_not_called()


def test_gdocs_publish_propagates_batch_update_failure() -> None:
    docs_service = Mock()
    documents = docs_service.documents.return_value
    documents.create.return_value.execute.return_value = {"documentId": "doc-id"}
    documents.batchUpdate.return_value.execute.side_effect = RuntimeError("Docs unavailable")

    with pytest.raises(RuntimeError, match="Docs unavailable"):
        gdocs.publish_markdown(
            content="# Bundle\n",
            title="Example",
            docs_service=docs_service,
        )

    documents.create.assert_called_once_with(body={"title": "Example"})
    documents.batchUpdate.assert_called_once_with(
        documentId="doc-id",
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": "# Bundle\n",
                    }
                }
            ]
        },
    )


@pytest.mark.parametrize(
    "response",
    [None, [], "doc-id", {}, {"documentId": None}, {"documentId": "  "}],
)
def test_gdocs_publish_rejects_missing_document_id(response: object) -> None:
    docs_service = Mock()
    documents = docs_service.documents.return_value
    documents.create.return_value.execute.return_value = response

    with pytest.raises(RuntimeError, match="did not contain a document ID"):
        gdocs.publish_markdown(
            content="# Bundle\n",
            title="Example",
            docs_service=docs_service,
        )

    documents.batchUpdate.assert_not_called()


def test_gdocs_publish_normalizes_document_id() -> None:
    docs_service = Mock()
    documents = docs_service.documents.return_value
    documents.create.return_value.execute.return_value = {"documentId": "  doc-id  "}

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="Example",
        docs_service=docs_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    documents.batchUpdate.assert_called_once_with(
        documentId="doc-id",
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": "# Bundle\n",
                    }
                }
            ]
        },
    )


def test_gdocs_publish_creates_document_in_folder() -> None:
    docs_service = Mock()
    drive_service = Mock()
    documents = docs_service.documents.return_value
    drive_service.files.return_value.create.return_value.execute.return_value = {"id": "doc-id"}

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="Example",
        folder_id="folder-123",
        docs_service=docs_service,
        drive_service=drive_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    drive_service.files.return_value.create.assert_called_once_with(
        body={
            "name": "Example",
            "mimeType": "application/vnd.google-apps.document",
            "parents": ["folder-123"],
        },
        fields="id",
    )
    documents.create.assert_not_called()
    documents.batchUpdate.assert_called_once_with(
        documentId="doc-id",
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": "# Bundle\n",
                    }
                }
            ]
        },
    )
    documents.batchUpdate.return_value.execute.assert_called_once_with()


@pytest.mark.parametrize("response", [None, [], "doc-id", {}, {"id": "  "}])
def test_gdocs_publish_rejects_missing_drive_file_id(response: object) -> None:
    docs_service = Mock()
    drive_service = Mock()
    drive_service.files.return_value.create.return_value.execute.return_value = response

    with pytest.raises(RuntimeError, match="did not contain a document ID"):
        gdocs.publish_markdown(
            content="# Bundle\n",
            title="Example",
            folder_id="folder-123",
            docs_service=docs_service,
            drive_service=drive_service,
        )

    docs_service.documents.return_value.batchUpdate.assert_not_called()


def test_gdocs_publish_normalizes_drive_file_id() -> None:
    docs_service = Mock()
    drive_service = Mock()
    documents = docs_service.documents.return_value
    drive_service.files.return_value.create.return_value.execute.return_value = {
        "id": "  doc-id  "
    }

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="Example",
        folder_id="folder-123",
        docs_service=docs_service,
        drive_service=drive_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    documents.batchUpdate.assert_called_once_with(
        documentId="doc-id",
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": "# Bundle\n",
                    }
                }
            ]
        },
    )


def test_gdocs_publish_builds_docs_service_without_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = object()
    credential_requests: list[bool] = []
    docs_credentials: list[object | None] = []
    docs_service = Mock()
    documents = docs_service.documents.return_value
    documents.create.return_value.execute.return_value = {"documentId": "doc-id"}
    build_drive_service = Mock()

    def fake_build_google_credentials(*, include_drive: bool) -> object:
        credential_requests.append(include_drive)
        return credentials

    def fake_build_docs_service(*, credentials: object | None = None) -> Mock:
        docs_credentials.append(credentials)
        return docs_service

    monkeypatch.setattr(gdocs, "_build_google_credentials", fake_build_google_credentials)
    monkeypatch.setattr(gdocs, "_build_docs_service", fake_build_docs_service)
    monkeypatch.setattr(gdocs, "_build_drive_service", build_drive_service)

    url = gdocs.publish_markdown(content="# Bundle\n", title="Example")

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    assert credential_requests == [False]
    assert docs_credentials == [credentials]
    build_drive_service.assert_not_called()
    documents.create.assert_called_once_with(body={"title": "Example"})
    documents.batchUpdate.assert_called_once()


def test_gdocs_publish_builds_drive_service_for_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = object()
    credential_requests: list[bool] = []
    docs_credentials: list[object | None] = []
    drive_credentials: list[object | None] = []
    docs_service = Mock()
    drive_service = Mock()
    documents = docs_service.documents.return_value
    drive_service.files.return_value.create.return_value.execute.return_value = {"id": "doc-id"}

    def fake_build_google_credentials(*, include_drive: bool) -> object:
        credential_requests.append(include_drive)
        return credentials

    def fake_build_docs_service(*, credentials: object | None = None) -> Mock:
        docs_credentials.append(credentials)
        return docs_service

    def fake_build_drive_service(*, credentials: object | None = None) -> Mock:
        drive_credentials.append(credentials)
        return drive_service

    monkeypatch.setattr(gdocs, "_build_google_credentials", fake_build_google_credentials)
    monkeypatch.setattr(gdocs, "_build_docs_service", fake_build_docs_service)
    monkeypatch.setattr(gdocs, "_build_drive_service", fake_build_drive_service)

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="Example",
        folder_id="folder-123",
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    assert credential_requests == [True]
    assert docs_credentials == [credentials]
    assert drive_credentials == [credentials]
    drive_service.files.return_value.create.assert_called_once_with(
        body={
            "name": "Example",
            "mimeType": "application/vnd.google-apps.document",
            "parents": ["folder-123"],
        },
        fields="id",
    )
    documents.create.assert_not_called()
    documents.batchUpdate.assert_called_once()


def test_gdocs_publish_builds_only_drive_service_for_injected_docs_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = object()
    credential_requests: list[bool] = []
    docs_service = Mock()
    drive_service = Mock()
    documents = docs_service.documents.return_value
    drive_service.files.return_value.create.return_value.execute.return_value = {"id": "doc-id"}
    build_docs_service = Mock()
    drive_credentials: list[object | None] = []

    def fake_build_google_credentials(*, include_drive: bool) -> object:
        credential_requests.append(include_drive)
        return credentials

    def fake_build_drive_service(*, credentials: object | None = None) -> Mock:
        drive_credentials.append(credentials)
        return drive_service

    monkeypatch.setattr(gdocs, "_build_google_credentials", fake_build_google_credentials)
    monkeypatch.setattr(gdocs, "_build_docs_service", build_docs_service)
    monkeypatch.setattr(gdocs, "_build_drive_service", fake_build_drive_service)

    url = gdocs.publish_markdown(
        content="# Bundle\n",
        title="Example",
        folder_id="folder-123",
        docs_service=docs_service,
    )

    assert url == "https://docs.google.com/document/d/doc-id/edit"
    assert credential_requests == [True]
    assert drive_credentials == [credentials]
    build_docs_service.assert_not_called()
    drive_service.files.return_value.create.assert_called_once_with(
        body={
            "name": "Example",
            "mimeType": gdocs.GOOGLE_DOC_MIME_TYPE,
            "parents": ["folder-123"],
        },
        fields="id",
    )
    documents.batchUpdate.assert_called_once()


def test_build_google_credentials_uses_docs_scope_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_scopes: list[list[str]] = []

    def fake_default(*, scopes: list[str]) -> tuple[object, None]:
        captured_scopes.append(scopes)
        return object(), None

    import google.auth

    monkeypatch.setattr(google.auth, "default", fake_default)

    gdocs._build_google_credentials(include_drive=False)

    assert captured_scopes == [[gdocs.GOOGLE_DOCS_SCOPE]]


def test_build_google_credentials_adds_drive_scope_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_scopes: list[list[str]] = []

    def fake_default(*, scopes: list[str]) -> tuple[object, None]:
        captured_scopes.append(scopes)
        return object(), None

    import google.auth

    monkeypatch.setattr(google.auth, "default", fake_default)

    gdocs._build_google_credentials(include_drive=True)

    assert captured_scopes == [
        [gdocs.GOOGLE_DOCS_SCOPE, gdocs.GOOGLE_DRIVE_FILE_SCOPE]
    ]


@pytest.mark.parametrize(
    ("include_drive", "expected_scopes"),
    [
        (False, [gdocs.GOOGLE_DOCS_SCOPE]),
        (True, [gdocs.GOOGLE_DOCS_SCOPE, gdocs.GOOGLE_DRIVE_FILE_SCOPE]),
    ],
)
def test_build_google_credentials_selects_installed_app_oauth_and_scopes(
    monkeypatch: pytest.MonkeyPatch, include_drive: bool, expected_scopes: list[str]
) -> None:
    credentials = object()
    build_installed = Mock(return_value=credentials)
    monkeypatch.setattr(gdocs, "_build_installed_app_oauth_credentials", build_installed)
    client_file = Path("client.json")
    token_file = Path("token.json")

    result = gdocs._build_google_credentials(
        include_drive=include_drive,
        oauth_client_file=client_file,
        oauth_token_file=token_file,
    )

    assert result is credentials
    build_installed.assert_called_once_with(
        client_file=client_file,
        token_file=token_file,
        scopes=expected_scopes,
    )


def test_installed_app_oauth_starts_local_server_with_requested_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_app_flow = cast(Any, importlib.import_module("google_auth_oauthlib.flow"))
    InstalledAppFlow = installed_app_flow.InstalledAppFlow

    credentials = Mock()
    flow = Mock()
    flow.run_local_server.return_value = credentials
    create_flow = Mock(return_value=flow)
    persist = Mock()
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", create_flow)
    monkeypatch.setattr(gdocs, "_persist_oauth_token", persist)
    scopes = [gdocs.GOOGLE_DOCS_SCOPE, gdocs.GOOGLE_DRIVE_FILE_SCOPE]
    client_file = Path("client.json")
    token_file = Path("token.json")

    result = gdocs._build_installed_app_oauth_credentials(
        client_file=client_file,
        token_file=token_file,
        scopes=scopes,
    )

    assert result is credentials
    create_flow.assert_called_once_with(str(client_file), scopes=scopes)
    flow.run_local_server.assert_called_once_with(
        port=0,
        access_type="offline",
        prompt="consent",
    )
    persist.assert_called_once_with(token_file, credentials)


def test_installed_app_oauth_failure_hides_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_app_flow = cast(Any, importlib.import_module("google_auth_oauthlib.flow"))
    InstalledAppFlow = installed_app_flow.InstalledAppFlow

    synthetic_secret = "synthetic-google-api-token-for-test"
    create_flow = Mock(side_effect=RuntimeError(synthetic_secret))
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", create_flow)

    with pytest.raises(gdocs.InstalledAppOAuthError) as error:
        gdocs._build_installed_app_oauth_credentials(
            client_file=Path("client.json"),
            token_file=Path("token.json"),
            scopes=[gdocs.GOOGLE_DOCS_SCOPE],
        )

    assert synthetic_secret not in str(error.value)


def test_persist_oauth_token_is_private(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    credentials = Mock()
    credentials.to_json.return_value = '{"refresh_token": "synthetic"}'

    gdocs._persist_oauth_token(token_file, credentials)

    assert token_file.read_text(encoding="utf-8") == '{"refresh_token": "synthetic"}'
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_prepare_oauth_token_file_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    token_file.symlink_to(target)

    with pytest.raises(ValueError, match="private regular file"):
        gdocs._prepare_oauth_token_file(token_file)


def test_stored_oauth_token_requires_every_requested_scope(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text(
        '{"scopes": ["https://www.googleapis.com/auth/documents"]}', encoding="utf-8"
    )

    assert gdocs._stored_oauth_token_has_scopes(token_file, [gdocs.GOOGLE_DOCS_SCOPE])
    assert not gdocs._stored_oauth_token_has_scopes(
        token_file,
        [gdocs.GOOGLE_DOCS_SCOPE, gdocs.GOOGLE_DRIVE_FILE_SCOPE],
    )


def test_build_google_credentials_reports_missing_google_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "google.auth", None)

    with pytest.raises(
        RuntimeError,
        match="Google API dependencies are not installed",
    ) as error:
        gdocs._build_google_credentials(include_drive=False)

    assert isinstance(error.value.__cause__, ImportError)


def test_google_api_build_reports_missing_google_api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", None)

    with pytest.raises(
        RuntimeError,
        match="Google API dependencies are not installed",
    ) as error:
        gdocs._google_api_build()

    assert isinstance(error.value.__cause__, ImportError)


def _http_error(status: object, content: bytes = b"") -> Exception:
    """Build a real googleapiclient HttpError, which the classifier matches by type."""
    errors = cast(Any, importlib.import_module("googleapiclient.errors"))
    response = Mock()
    response.status = status
    return cast(Exception, errors.HttpError(resp=response, content=content))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "Google API authentication failed (HTTP 401); check Application Default Credentials"),
        (403, "Google API request was forbidden (HTTP 403); check Google Docs or Drive access"),
        (404, "Google API resource was not found (HTTP 404); check the configured resource ID"),
        (429, "Google API rate limit reached (HTTP 429); retry later"),
        (500, "Google API service failed (HTTP 500); retry later"),
        (503, "Google API service failed (HTTP 503); retry later"),
        (400, "Google API request failed (HTTP 400); check the publish configuration"),
    ],
)
def test_publish_failure_message_classifies_http_status(status: int, expected: str) -> None:
    assert gdocs.publish_failure_message(_http_error(status)) == expected


def test_publish_failure_message_handles_missing_http_status() -> None:
    assert gdocs.publish_failure_message(_http_error(None)) == "Google API request failed"


def test_publish_failure_message_reports_installed_app_oauth_failure() -> None:
    error = gdocs.InstalledAppOAuthError("installed-app OAuth configuration failed")

    assert gdocs.publish_failure_message(error) == (
        "Google installed-app OAuth failed; check the OAuth client and token files"
    )


@pytest.mark.parametrize(
    "exception_name", ["DefaultCredentialsError", "RefreshError", "UserAccessTokenError"]
)
def test_publish_failure_message_reports_adc_failure(exception_name: str) -> None:
    exceptions = cast(Any, importlib.import_module("google.auth.exceptions"))
    error = cast(BaseException, getattr(exceptions, exception_name)("synthetic detail"))

    assert gdocs.publish_failure_message(error) == (
        "Google authentication failed; check Application Default Credentials"
    )


def test_publish_failure_message_falls_back_for_unrecognized_errors() -> None:
    error = RuntimeError("synthetic-google-api-token-for-test")

    message = gdocs.publish_failure_message(error)

    assert message == "Google Docs API request was unsuccessful"
    assert "synthetic-google-api-token-for-test" not in message


def test_publish_failure_message_adds_allowlisted_403_status_and_reason() -> None:
    content = json.dumps(
        {
            "error": {
                "status": "PERMISSION_DENIED",
                "errors": [{"reason": "forbidden"}],
            }
        }
    ).encode("utf-8")

    assert gdocs.publish_failure_message(_http_error(403, content)) == (
        "Google API request was forbidden (HTTP 403, status PERMISSION_DENIED, reason forbidden); "
        "check Google Docs or Drive access"
    )


def test_publish_failure_message_omits_unrecognized_403_status_and_reason() -> None:
    content = json.dumps(
        {
            "error": {
                "status": "SOMETHING_NEW",
                "errors": [{"reason": "unlistedReason"}],
            }
        }
    ).encode("utf-8")

    assert gdocs.publish_failure_message(_http_error(403, content)) == (
        "Google API request was forbidden (HTTP 403); check Google Docs or Drive access"
    )


def test_publish_failure_message_never_renders_provider_403_body() -> None:
    synthetic_secret = "synthetic-google-api-token-for-test"
    content = json.dumps(
        {
            "error": {
                "status": "PERMISSION_DENIED",
                "message": f"Request had insufficient authentication scopes: {synthetic_secret}",
                "errors": [{"reason": "forbidden", "message": synthetic_secret}],
                "details": [{"metadata": {"token": synthetic_secret}}],
            }
        }
    ).encode("utf-8")

    message = gdocs.publish_failure_message(_http_error(403, content))

    assert synthetic_secret not in message
    assert "insufficient authentication scopes" not in message
    assert "status PERMISSION_DENIED, reason forbidden" in message


def test_publish_failure_message_ignores_oversized_403_body() -> None:
    synthetic_secret = "synthetic-google-api-token-for-test"
    payload = {
        "error": {
            "status": "PERMISSION_DENIED",
            "errors": [{"reason": "forbidden"}],
            "padding": synthetic_secret + "x" * gdocs._MAX_GOOGLE_ERROR_CONTENT_BYTES,
        }
    }
    content = json.dumps(payload).encode("utf-8")
    assert len(content) > gdocs._MAX_GOOGLE_ERROR_CONTENT_BYTES

    message = gdocs.publish_failure_message(_http_error(403, content))

    assert message == (
        "Google API request was forbidden (HTTP 403); check Google Docs or Drive access"
    )
    assert synthetic_secret not in message


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'{"error": "forbidden"}',
        b'{"error": {"errors": "forbidden"}}',
    ],
)
def test_publish_failure_message_ignores_unusable_403_bodies(content: bytes) -> None:
    assert gdocs.publish_failure_message(_http_error(403, content)) == (
        "Google API request was forbidden (HTTP 403); check Google Docs or Drive access"
    )


def test_publish_failure_message_reports_missing_publish_extra() -> None:
    error = gdocs.GoogleDependenciesMissingError(gdocs._MISSING_GOOGLE_DEPENDENCIES_MESSAGE)

    message = gdocs.publish_failure_message(error)

    assert "knowledge-adapters[publish]" in message
    assert message == gdocs._MISSING_GOOGLE_DEPENDENCIES_MESSAGE


@pytest.mark.parametrize(
    ("module", "call"),
    [
        ("google.auth", lambda: gdocs._build_google_credentials(include_drive=False)),
        ("googleapiclient.discovery", gdocs._google_api_build),
    ],
)
def test_missing_google_dependencies_raise_the_classified_error(
    monkeypatch: pytest.MonkeyPatch, module: str, call: Any
) -> None:
    monkeypatch.setitem(sys.modules, module, None)

    with pytest.raises(gdocs.GoogleDependenciesMissingError) as error:
        call()

    assert gdocs.publish_failure_message(error.value) == gdocs._MISSING_GOOGLE_DEPENDENCIES_MESSAGE
