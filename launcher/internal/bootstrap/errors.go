package bootstrap

import "fmt"

const (
	ErrCodeLatestFetchFailed           = "latest-fetch-failed"
	ErrCodeManifestFetchFailed         = "manifest-fetch-failed"
	ErrCodeManifestIntegrityFailed     = "manifest-integrity-failed"
	ErrCodeBootstrapUpgradeRequired    = "bootstrap-upgrade-required"
	ErrCodeDownloadFailed              = "download-failed"
	ErrCodePackageIntegrityFailed      = "package-integrity-failed"
	ErrCodeStageFailed                 = "stage-failed"
	ErrCodeSwitchFailed                = "switch-failed"
	ErrCodeCandidateReadyTimeout       = "candidate-ready-timeout"
	ErrCodeCandidateExit               = "candidate-exit"
	ErrCodeRollbackFailed              = "rollback-failed"
	ErrCodeBootstrapSelfUpdateFailed   = "bootstrap-self-update-failed"
	ErrCodeAPIVersionMismatch          = "api-version-mismatch"
	ErrCodeRootNotWritable             = "root-not-writable"
	ErrCodePermissionDenied            = "permission-denied"
)

type BootstrapError struct {
	Code    string         `json:"code"`
	Message string         `json:"message"`
	Details map[string]any `json:"details,omitempty"`
	Cause   error          `json:"-"`
}

func NewBootstrapError(code string, message string, details map[string]any, cause error) *BootstrapError {
	return &BootstrapError{
		Code:    code,
		Message: message,
		Details: details,
		Cause:   cause,
	}
}

func (err *BootstrapError) Error() string {
	if err == nil {
		return ""
	}
	if err.Cause == nil {
		return fmt.Sprintf("%s: %s", err.Code, err.Message)
	}
	return fmt.Sprintf("%s: %s: %v", err.Code, err.Message, err.Cause)
}

func (err *BootstrapError) Unwrap() error {
	if err == nil {
		return nil
	}
	return err.Cause
}
