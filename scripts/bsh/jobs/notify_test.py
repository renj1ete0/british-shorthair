"""Verify Telegram credentials without waiting for something to break.

    python run_job.py notify_test

Sends one alert and one digest, so both paths are exercised: alerts are rate-limited
and deduplicated, digests are not, and a token can be valid for one and misconfigured
for the other only if the chat id is wrong.

Reports precisely which half of the configuration is missing rather than failing
silently, because "no notification arrived" has several possible causes and only some
of them are this project's fault.
"""

from .. import notify
from ..logging_setup import now
from ..registry import job


@job(
    "notify_test",
    schedule=None,
    description="Send a test alert and digest to confirm Telegram is configured",
    alert_on_failure=False,
)
def collect(logger, record, settings):
    if not settings.telegram_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    if not settings.telegram_chat_id:
        # The id cannot be inferred from the token - a bot has no owner. But anyone who
        # has messaged the bot shows up in getUpdates, so look there before giving up.
        candidates = notify.discover_chat_ids(settings.telegram_token, logger=logger)
        if not candidates:
            raise RuntimeError(
                "TELEGRAM_CHAT_ID is not set, and no chats were found. Send your bot a "
                "message (any text) in Telegram, then run this again and it will tell "
                "you the id to put in .env."
            )
        logger.info("chats that have messaged this bot:")
        for chat_id, label, kind in candidates:
            logger.info("    TELEGRAM_CHAT_ID=%s    (%s, %s)", chat_id, label, kind)
        raise RuntimeError(
            f"TELEGRAM_CHAT_ID is not set. Add one of the ids above to .env "
            f"(use {candidates[0][0]} for a direct message from the bot to you)."
        )

    logger.info("token ...%s, chat id %s",
                settings.telegram_token[-6:], settings.telegram_chat_id)

    stamp = now().strftime("%Y-%m-%d %H:%M:%S")

    # A unique key each run, or the cooldown would suppress a second test.
    alert_ok = notify.alert(
        "Test alert",
        f"If you can read this, immediate failure alerts will reach you.\nSent {stamp}.",
        key=f"notify_test:{stamp}",
        logger=logger,
    )
    digest_ok = notify.digest(
        "Test digest",
        "If you can read this, the daily summary will reach you too.\n"
        f"Sent {stamp} from the collector container.",
        logger=logger,
    )

    record.notes["alert_delivered"] = alert_ok
    record.notes["digest_delivered"] = digest_ok

    if not (alert_ok and digest_ok):
        raise RuntimeError(
            "Telegram rejected the message. The usual causes are a chat id that does "
            "not match the bot, or never having sent the bot a message first - a bot "
            "cannot open a conversation with you."
        )

    record.items_ok = 2
    logger.info("both messages delivered; Telegram is configured correctly")
