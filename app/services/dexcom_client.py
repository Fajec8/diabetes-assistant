import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib import error, parse, request

from dotenv import load_dotenv


load_dotenv()


class DexcomAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code


def _required_env(
    name: str,
) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"{name} environment variable is not set"
        )

    return value


def dexcom_environment() -> str:
    value = os.getenv(
        "DEXCOM_ENVIRONMENT",
        "sandbox",
    ).strip().lower()

    if value not in {
        "sandbox",
        "production",
    }:
        raise RuntimeError(
            "DEXCOM_ENVIRONMENT must be "
            "'sandbox' or 'production'"
        )

    return value


def dexcom_base_url() -> str:
    if dexcom_environment() == "sandbox":
        return (
            "https://sandbox-api.dexcom.com"
        )

    return "https://api.dexcom.com"


def dexcom_redirect_uri() -> str:
    return _required_env(
        "DEXCOM_REDIRECT_URI"
    )


def dexcom_is_configured() -> bool:
    required = (
        "DEXCOM_CLIENT_ID",
        "DEXCOM_CLIENT_SECRET",
        "DEXCOM_REDIRECT_URI",
        "DEXCOM_STATE_SECRET",
    )

    return all(
        bool(os.getenv(name))
        for name in required
    )


def build_oauth_state(
    user_id: uuid.UUID,
) -> str:
    state_secret = _required_env(
        "DEXCOM_STATE_SECRET"
    )

    timestamp = int(
        time.time()
    )

    nonce = secrets.token_urlsafe(
        16
    )

    payload = (
        f"{user_id}|"
        f"{timestamp}|"
        f"{nonce}"
    )

    payload_encoded = (
        base64
        .urlsafe_b64encode(
            payload.encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )

    signature = hmac.new(
        state_secret.encode("utf-8"),
        payload_encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    return (
        f"{payload_encoded}."
        f"{signature}"
    )


def verify_oauth_state(
    state: str,
    max_age_seconds: int = 600,
) -> uuid.UUID:
    try:
        payload_encoded, signature = (
            state.split(
                ".",
                1,
            )
        )
    except ValueError as exc:
        raise ValueError(
            "Invalid Dexcom OAuth state"
        ) from exc

    state_secret = _required_env(
        "DEXCOM_STATE_SECRET"
    )

    expected_signature = hmac.new(
        state_secret.encode("utf-8"),
        payload_encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        signature,
        expected_signature,
    ):
        raise ValueError(
            "Invalid Dexcom OAuth state signature"
        )

    padding = (
        "="
        * (
            -len(payload_encoded)
            % 4
        )
    )

    try:
        payload = (
            base64
            .urlsafe_b64decode(
                payload_encoded
                + padding
            )
            .decode("utf-8")
        )

        user_id_text, timestamp_text, _ = (
            payload.split(
                "|",
                2,
            )
        )

        timestamp = int(
            timestamp_text
        )

        user_id = uuid.UUID(
            user_id_text
        )

    except (
        ValueError,
        UnicodeDecodeError,
    ) as exc:
        raise ValueError(
            "Invalid Dexcom OAuth state payload"
        ) from exc

    age = (
        int(time.time())
        - timestamp
    )

    if (
        age < 0
        or age > max_age_seconds
    ):
        raise ValueError(
            "Dexcom OAuth state expired"
        )

    return user_id


def build_authorization_url(
    user_id: uuid.UUID,
) -> str:
    state = build_oauth_state(
        user_id
    )

    query = parse.urlencode(
        {
            "client_id":
                _required_env(
                    "DEXCOM_CLIENT_ID"
                ),

            "redirect_uri":
                dexcom_redirect_uri(),

            "response_type":
                "code",

            "scope":
                "offline_access",

            "state":
                state,
        }
    )

    return (
        f"{dexcom_base_url()}"
        f"/v3/oauth2/login?"
        f"{query}"
    )


def _decode_error_body(
    exc: error.HTTPError,
) -> str:
    try:
        body = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        parsed = json.loads(
            body
        )

        if isinstance(
            parsed,
            dict,
        ):
            return str(
                parsed.get(
                    "error_description"
                )
                or parsed.get(
                    "error"
                )
                or parsed.get(
                    "message"
                )
                or (
                    f"HTTP "
                    f"{exc.code}"
                )
            )

        return (
            f"HTTP {exc.code}"
        )

    except Exception:
        return (
            f"HTTP {exc.code}"
        )


def _post_form(
    path: str,
    fields: dict[str, str],
) -> dict:
    encoded = (
        parse.urlencode(
            fields
        )
        .encode("utf-8")
    )

    req = request.Request(
        url=(
            f"{dexcom_base_url()}"
            f"{path}"
        ),
        data=encoded,
        method="POST",
        headers={
            "Content-Type":
                (
                    "application/"
                    "x-www-form-urlencoded"
                ),
            "Accept":
                "application/json",
        },
    )

    try:
        with request.urlopen(
            req,
            timeout=30,
        ) as response:
            body = (
                response.read()
                .decode("utf-8")
            )

    except error.HTTPError as exc:
        raise DexcomAPIError(
            _decode_error_body(
                exc
            ),
            status_code=exc.code,
        ) from exc

    except error.URLError as exc:
        raise DexcomAPIError(
            "Dexcom API is unreachable"
        ) from exc

    try:
        return json.loads(
            body
        )

    except json.JSONDecodeError as exc:
        raise DexcomAPIError(
            "Dexcom returned invalid JSON"
        ) from exc


def exchange_authorization_code(
    code: str,
) -> dict:
    return _post_form(
        "/v3/oauth2/token",
        {
            "grant_type":
                "authorization_code",

            "code":
                code,

            "redirect_uri":
                dexcom_redirect_uri(),

            "client_id":
                _required_env(
                    "DEXCOM_CLIENT_ID"
                ),

            "client_secret":
                _required_env(
                    "DEXCOM_CLIENT_SECRET"
                ),
        },
    )


def refresh_access_token(
    refresh_token: str,
) -> dict:
    return _post_form(
        "/v3/oauth2/token",
        {
            "grant_type":
                "refresh_token",

            "refresh_token":
                refresh_token,

            "client_id":
                _required_env(
                    "DEXCOM_CLIENT_ID"
                ),

            "client_secret":
                _required_env(
                    "DEXCOM_CLIENT_SECRET"
                ),
        },
    )


def _format_dexcom_datetime(
    value: datetime,
) -> str:
    if (
        value.tzinfo
        is None
    ):
        value = value.replace(
            tzinfo=timezone.utc
        )

    value = value.astimezone(
        timezone.utc
    )

    return value.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def get_egvs(
    access_token: str,
    start_at: datetime,
    end_at: datetime,
) -> dict:
    query = parse.urlencode(
        {
            "startDate":
                _format_dexcom_datetime(
                    start_at
                ),

            "endDate":
                _format_dexcom_datetime(
                    end_at
                ),
        }
    )

    req = request.Request(
        url=(
            f"{dexcom_base_url()}"
            "/v3/users/self/egvs?"
            f"{query}"
        ),
        method="GET",
        headers={
            "Authorization":
                (
                    "Bearer "
                    f"{access_token}"
                ),

            "Accept":
                "application/json",
        },
    )

    try:
        with request.urlopen(
            req,
            timeout=30,
        ) as response:
            body = (
                response.read()
                .decode("utf-8")
            )

    except error.HTTPError as exc:
        raise DexcomAPIError(
            _decode_error_body(
                exc
            ),
            status_code=exc.code,
        ) from exc

    except error.URLError as exc:
        raise DexcomAPIError(
            "Dexcom API is unreachable"
        ) from exc

    try:
        return json.loads(
            body
        )

    except json.JSONDecodeError as exc:
        raise DexcomAPIError(
            "Dexcom returned invalid JSON"
        ) from exc