class PFDAnalysisError(Exception):
    pass


class CancelledByClientError(PFDAnalysisError):
    """客户端发起取消时，工作线程在检查点主动抛出。"""
    pass


class AnalysisError(PFDAnalysisError):
    pass


class ConfigurationError(PFDAnalysisError):
    pass


class ImageProcessingError(PFDAnalysisError):
    pass


class APIError(PFDAnalysisError):
    pass


class ParseError(PFDAnalysisError):
    pass


class ValidationError(PFDAnalysisError):
    pass


class PFDFileNotFoundError(PFDAnalysisError):
    pass


class DirectoryNotFoundError(PFDAnalysisError):
    pass
