"""알림 서비스 모듈.

배치 작업 실패 시 Slack/Discord 웹훅을 통해 알림을 전송합니다.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class NotificationService:
    """알림 서비스."""

    def __init__(self, webhook_url: Optional[str] = None):
        """알림 서비스 초기화.

        Args:
            webhook_url: Slack 또는 Discord 웹훅 URL
        """
        self.webhook_url = webhook_url or getattr(settings, "notification_webhook_url", None)
        self.webhook_enabled = bool(self.webhook_url)

        # Telegram 설정
        self.telegram_bot_token = getattr(settings, "telegram_bot_token", None)
        self.telegram_chat_id = getattr(settings, "telegram_chat_id", None)
        self.telegram_enabled = (
            getattr(settings, "telegram_enabled", False)
            and self.telegram_bot_token
            and self.telegram_chat_id
        )

    async def send_batch_failure(
        self,
        job_type: str,
        error_message: str,
        failed_count: int,
        total_count: int,
        started_at: datetime,
    ) -> bool:
        """배치 작업 실패 알림 전송.

        Args:
            job_type: 작업 유형 (예: "daily_full", "sync_prices")
            error_message: 에러 메시지
            failed_count: 실패한 항목 수
            total_count: 전체 항목 수
            started_at: 작업 시작 시각

        Returns:
            알림 전송 성공 여부
        """
        if not self.webhook_enabled:
            logger.debug("Notification webhook not configured, skipping")
            return False

        try:
            duration = (datetime.utcnow() - started_at).total_seconds()
            success_rate = ((total_count - failed_count) / total_count * 100) if total_count > 0 else 0

            # Slack/Discord 공통 포맷 (Discord는 Slack 웹훅 형식도 지원)
            payload = {
                "text": f"⚠️ RS Scanner 배치 작업 실패",
                "attachments": [
                    {
                        "color": "danger",
                        "title": f"{job_type} 작업 실패",
                        "fields": [
                            {
                                "title": "에러 메시지",
                                "value": error_message[:500],  # 길이 제한
                                "short": False,
                            },
                            {
                                "title": "실패율",
                                "value": f"{failed_count}/{total_count} ({100 - success_rate:.1f}%)",
                                "short": True,
                            },
                            {
                                "title": "실행 시간",
                                "value": f"{duration:.1f}초",
                                "short": True,
                            },
                            {
                                "title": "발생 시각",
                                "value": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                                "short": True,
                            },
                        ],
                    }
                ],
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()

            logger.info(f"Batch failure notification sent: {job_type}")
            return True

        except httpx.HTTPError as e:
            logger.error(f"Failed to send notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending notification: {e}")
            return False

    async def send_batch_success(
        self,
        job_type: str,
        total_count: int,
        duration_seconds: float,
    ) -> bool:
        """배치 작업 성공 알림 전송 (선택적).

        Args:
            job_type: 작업 유형
            total_count: 처리된 항목 수
            duration_seconds: 실행 시간 (초)

        Returns:
            알림 전송 성공 여부
        """
        if not self.webhook_enabled:
            return False

        try:
            payload = {
                "text": f"✅ RS Scanner 배치 작업 완료",
                "attachments": [
                    {
                        "color": "good",
                        "title": f"{job_type} 작업 성공",
                        "fields": [
                            {
                                "title": "처리 건수",
                                "value": f"{total_count}개",
                                "short": True,
                            },
                            {
                                "title": "실행 시간",
                                "value": f"{duration_seconds:.1f}초",
                                "short": True,
                            },
                        ],
                    }
                ],
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()

            logger.debug(f"Batch success notification sent: {job_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to send success notification: {e}")
            return False

    def send_batch_failure_sync(
        self,
        job_type: str,
        error_message: str,
        failed_count: int,
        total_count: int,
        started_at: datetime,
    ) -> bool:
        """배치 작업 실패 알림 전송 (동기 버전).

        동기 코드에서 사용하기 위한 래퍼 함수.

        Args:
            job_type: 작업 유형
            error_message: 에러 메시지
            failed_count: 실패한 항목 수
            total_count: 전체 항목 수
            started_at: 작업 시작 시각

        Returns:
            알림 전송 성공 여부
        """
        if not self.webhook_enabled:
            logger.debug("Notification webhook not configured, skipping")
            return False

        try:
            duration = (datetime.utcnow() - started_at).total_seconds()
            success_rate = ((total_count - failed_count) / total_count * 100) if total_count > 0 else 0

            payload = {
                "text": f"⚠️ RS Scanner 배치 작업 실패",
                "attachments": [
                    {
                        "color": "danger",
                        "title": f"{job_type} 작업 실패",
                        "fields": [
                            {
                                "title": "에러 메시지",
                                "value": error_message[:500],
                                "short": False,
                            },
                            {
                                "title": "실패율",
                                "value": f"{failed_count}/{total_count} ({100 - success_rate:.1f}%)",
                                "short": True,
                            },
                            {
                                "title": "실행 시간",
                                "value": f"{duration:.1f}초",
                                "short": True,
                            },
                            {
                                "title": "발생 시각",
                                "value": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                                "short": True,
                            },
                        ],
                    }
                ],
            }

            # httpx 동기 클라이언트 사용
            with httpx.Client(timeout=10.0) as client:
                response = client.post(self.webhook_url, json=payload)
                response.raise_for_status()

            logger.info(f"Batch failure notification sent: {job_type}")
            return True

        except httpx.HTTPError as e:
            logger.error(f"Failed to send notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending notification: {e}")
            return False

    def send_batch_success_sync(
        self,
        job_type: str,
        total_count: int,
        duration_seconds: float,
    ) -> bool:
        """배치 작업 성공 알림 전송 (동기 버전).

        Slack/Discord 웹훅과 Telegram 모두 전송.

        Args:
            job_type: 작업 유형
            total_count: 처리된 항목 수
            duration_seconds: 실행 시간 (초)

        Returns:
            알림 전송 성공 여부
        """
        # notification_on_success 설정 확인
        if not getattr(settings, "notification_on_success", False):
            logger.debug("Success notifications disabled, skipping")
            return False

        webhook_result = False
        telegram_result = False

        # Slack/Discord 웹훅 전송
        if self.webhook_enabled:
            try:
                payload = {
                    "text": f"✅ RS Scanner 배치 작업 완료",
                    "attachments": [
                        {
                            "color": "good",
                            "title": f"{job_type} 작업 성공",
                            "fields": [
                                {
                                    "title": "처리 건수",
                                    "value": f"{total_count}개",
                                    "short": True,
                                },
                                {
                                    "title": "실행 시간",
                                    "value": f"{duration_seconds:.1f}초",
                                    "short": True,
                                },
                            ],
                        }
                    ],
                }

                with httpx.Client(timeout=10.0) as client:
                    response = client.post(self.webhook_url, json=payload)
                    response.raise_for_status()

                logger.debug(f"Batch success notification sent (webhook): {job_type}")
                webhook_result = True

            except Exception as e:
                logger.error(f"Failed to send webhook success notification: {e}")

        # Telegram 전송
        if self.telegram_enabled:
            telegram_result = self._send_telegram_success_sync(job_type, total_count, duration_seconds)

        return webhook_result or telegram_result


    def _send_telegram_failure_sync(
        self,
        job_type: str,
        error_message: str,
        failed_count: int,
        total_count: int,
        started_at: datetime,
    ) -> bool:
        """Telegram 실패 알림 전송 (동기).

        Args:
            job_type: 작업 유형
            error_message: 에러 메시지
            failed_count: 실패한 항목 수
            total_count: 전체 항목 수
            started_at: 작업 시작 시각

        Returns:
            알림 전송 성공 여부
        """
        try:
            duration = (datetime.utcnow() - started_at).total_seconds()
            success_rate = ((total_count - failed_count) / total_count * 100) if total_count > 0 else 0

            message = (
                f"⚠️ *RS Scanner 배치 작업 실패*\n\n"
                f"*작업 유형*: {job_type}\n"
                f"*에러 메시지*: {error_message[:200]}\n"
                f"*실패율*: {failed_count}/{total_count} ({100 - success_rate:.1f}%)\n"
                f"*실행 시간*: {duration:.1f}초\n"
                f"*발생 시각*: {started_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()

            logger.info(f"Batch failure notification sent (telegram): {job_type}")
            return True

        except httpx.HTTPError as e:
            logger.error(f"Failed to send telegram failure notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending telegram failure notification: {e}")
            return False

    def _send_telegram_success_sync(
        self,
        job_type: str,
        total_count: int,
        duration_seconds: float,
    ) -> bool:
        """Telegram 성공 알림 전송 (동기).

        Args:
            job_type: 작업 유형
            total_count: 처리된 항목 수
            duration_seconds: 실행 시간 (초)

        Returns:
            알림 전송 성공 여부
        """
        try:
            message = (
                f"✅ *RS Scanner 배치 작업 완료*\n\n"
                f"*작업 유형*: {job_type}\n"
                f"*처리 건수*: {total_count:,}개\n"
                f"*실행 시간*: {duration_seconds:.1f}초 (약 {duration_seconds/3600:.1f}시간)"
            )

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()

            logger.info(f"Batch success notification sent (telegram): {job_type}")
            return True

        except httpx.HTTPError as e:
            logger.error(f"Failed to send telegram success notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending telegram success notification: {e}")
            return False


# 전역 notification service 인스턴스
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """전역 알림 서비스 인스턴스 반환."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
