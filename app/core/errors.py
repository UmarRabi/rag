class ServiceError(Exception):
    def __init__(self, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers or {}


class NotFoundError(ServiceError):
    pass


class ConflictError(ServiceError):
    pass


class InvalidContentError(ServiceError):
    pass


class UnsupportedMediaTypeError(ServiceError):
    pass


class PayloadTooLargeError(ServiceError):
    pass


class UnauthorizedError(ServiceError):
    pass


class ServiceUnavailableError(ServiceError):
    pass


class ForbiddenError(ServiceError):
    pass


class RateLimitedError(ServiceError):
    pass
