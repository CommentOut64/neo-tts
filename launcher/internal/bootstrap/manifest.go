package bootstrap

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type ChannelLatest struct {
	SchemaVersion       int       `json:"schemaVersion"`
	Channel             string    `json:"channel"`
	EnableDevRelease    bool      `json:"enableDevRelease"`
	ReleaseID           string    `json:"releaseId"`
	ReleaseKind         string    `json:"releaseKind"`
	ManifestURL         string    `json:"manifestUrl"`
	ManifestSHA256      string    `json:"manifestSha256"`
	MinBootstrapVersion string    `json:"minBootstrapVersion"`
	PublishedAt         time.Time `json:"publishedAt"`
}

type RemotePackage struct {
	Version   string `json:"version"`
	URL       string `json:"url"`
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"sizeBytes,omitempty"`
}

type ReleaseManifest struct {
	SchemaVersion int                      `json:"schemaVersion"`
	ReleaseID     string                   `json:"releaseId"`
	Channel       string                   `json:"channel"`
	ReleaseKind   string                   `json:"releaseKind"`
	NotesURL      string                   `json:"notesUrl,omitempty"`
	Packages      map[string]RemotePackage `json:"packages"`
}

type UpdateStatus string

const (
	UpdateStatusIdle                     UpdateStatus = "idle"
	UpdateStatusUpToDate                 UpdateStatus = "up-to-date"
	UpdateStatusBootstrapUpgradeRequired UpdateStatus = "bootstrap-upgrade-required"
	UpdateStatusUpdateAvailable          UpdateStatus = "update-available"
	UpdateStatusDownloading              UpdateStatus = "downloading"
	UpdateStatusReadyToRestart           UpdateStatus = "ready-to-restart"
	UpdateStatusError                    UpdateStatus = "error"
)

type CheckUpdateRequest struct {
	Channel   string `json:"channel"`
	Automatic bool   `json:"automatic"`
}

type CheckUpdateResponse struct {
	Status                 UpdateStatus    `json:"status"`
	ReleaseID              string          `json:"releaseId,omitempty"`
	NotesURL               string          `json:"notesUrl,omitempty"`
	ChangedPackages        []string        `json:"changedPackages,omitempty"`
	EstimatedDownloadBytes int64           `json:"estimatedDownloadBytes,omitempty"`
	MinBootstrapVersion    string          `json:"minBootstrapVersion,omitempty"`
	ErrorCode              string          `json:"errorCode,omitempty"`
	ErrorMessage           string          `json:"errorMessage,omitempty"`
	Progress               *UpdateProgress `json:"progress,omitempty"`
}

type UpdateCheckOptions struct {
	Client              *http.Client
	LatestURL           string
	CurrentState        CurrentState
	BootstrapVersion    string
	AllowedPackageOrder []string
}

func CheckForUpdate(ctx context.Context, options UpdateCheckOptions) (CheckUpdateResponse, error) {
	client := options.Client
	if client == nil {
		client = http.DefaultClient
	}

	latest, err := fetchLatestMetadata(ctx, client, options.LatestURL)
	if err != nil {
		return CheckUpdateResponse{}, err
	}

	if latest.ReleaseID == options.CurrentState.ReleaseID {
		return CheckUpdateResponse{Status: UpdateStatusUpToDate, ReleaseID: latest.ReleaseID}, nil
	}

	if compareSemver(options.BootstrapVersion, latest.MinBootstrapVersion) < 0 {
		return CheckUpdateResponse{
			Status:              UpdateStatusBootstrapUpgradeRequired,
			ReleaseID:           latest.ReleaseID,
			MinBootstrapVersion: latest.MinBootstrapVersion,
		}, nil
	}

	manifest, err := fetchAndValidateManifest(ctx, client, latest.ManifestURL, latest.ManifestSHA256)
	if err != nil {
		return CheckUpdateResponse{}, err
	}

	order := options.AllowedPackageOrder
	if len(order) == 0 {
		order = DefaultPackageOrder()
	}

	changedPackages := make([]string, 0, len(order))
	var estimatedBytes int64
	for _, packageID := range order {
		remotePackage, ok := manifest.Packages[packageID]
		if !ok {
			continue
		}
		currentPackage, ok := options.CurrentState.Packages[packageID]
		if ok && currentPackage.Version == remotePackage.Version {
			continue
		}
		changedPackages = append(changedPackages, packageID)
		estimatedBytes += remotePackage.SizeBytes
	}

	if len(changedPackages) == 0 {
		return CheckUpdateResponse{Status: UpdateStatusUpToDate, ReleaseID: latest.ReleaseID}, nil
	}

	return CheckUpdateResponse{
		Status:                 UpdateStatusUpdateAvailable,
		ReleaseID:              manifest.ReleaseID,
		NotesURL:               manifest.NotesURL,
		ChangedPackages:        changedPackages,
		EstimatedDownloadBytes: estimatedBytes,
	}, nil
}

func FetchLatestRelease(
	ctx context.Context,
	client *http.Client,
	latestURL string,
) (ChannelLatest, ReleaseManifest, error) {
	if client == nil {
		client = http.DefaultClient
	}
	latest, err := fetchLatestMetadata(ctx, client, latestURL)
	if err != nil {
		return ChannelLatest{}, ReleaseManifest{}, err
	}

	manifest, err := fetchAndValidateManifest(ctx, client, latest.ManifestURL, latest.ManifestSHA256)
	if err != nil {
		return ChannelLatest{}, ReleaseManifest{}, err
	}
	return latest, manifest, nil
}

func fetchLatestMetadata(ctx context.Context, client *http.Client, latestURL string) (ChannelLatest, error) {
	var latest ChannelLatest
	if err := fetchJSON(ctx, client, latestURL, &latest); err != nil {
		return ChannelLatest{}, NewBootstrapError(
			ErrCodeLatestFetchFailed,
			"failed to fetch latest release metadata",
			map[string]any{"url": latestURL},
			err,
		)
	}
	return latest, nil
}

func fetchAndValidateManifest(
	ctx context.Context,
	client *http.Client,
	manifestURL string,
	expectedSHA256 string,
) (ReleaseManifest, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, manifestURL, nil)
	if err != nil {
		return ReleaseManifest{}, NewBootstrapError(
			ErrCodeManifestFetchFailed,
			"failed to build manifest request",
			map[string]any{"url": manifestURL},
			err,
		)
	}
	response, err := client.Do(request)
	if err != nil {
		return ReleaseManifest{}, NewBootstrapError(
			ErrCodeManifestFetchFailed,
			"failed to fetch manifest",
			map[string]any{"url": manifestURL},
			err,
		)
	}
	defer response.Body.Close()

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return ReleaseManifest{}, NewBootstrapError(
			ErrCodeManifestFetchFailed,
			fmt.Sprintf("manifest returned %d", response.StatusCode),
			map[string]any{"url": manifestURL, "statusCode": response.StatusCode},
			nil,
		)
	}

	payload, err := io.ReadAll(response.Body)
	if err != nil {
		return ReleaseManifest{}, NewBootstrapError(
			ErrCodeManifestFetchFailed,
			"failed to read manifest payload",
			map[string]any{"url": manifestURL},
			err,
		)
	}
	if sha256HexString(payload) != strings.ToLower(strings.TrimSpace(expectedSHA256)) {
		return ReleaseManifest{}, NewBootstrapError(
			ErrCodeManifestIntegrityFailed,
			"manifest sha256 mismatch",
			map[string]any{"url": manifestURL},
			nil,
		)
	}

	var manifest ReleaseManifest
	decoder := json.NewDecoder(strings.NewReader(string(payload)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&manifest); err != nil {
		return ReleaseManifest{}, NewBootstrapError(
			ErrCodeManifestFetchFailed,
			"failed to decode manifest payload",
			map[string]any{"url": manifestURL},
			err,
		)
	}
	return manifest, nil
}

func fetchJSON(ctx context.Context, client *http.Client, requestURL string, target any) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, requestURL, nil)
	if err != nil {
		return err
	}
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("unexpected status code %d", response.StatusCode)
	}
	decoder := json.NewDecoder(response.Body)
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}

func DefaultPackageOrder() []string {
	return []string{
		"bootstrap",
		"update-agent",
		"shell",
		"app-core",
		"runtime",
		"models",
		"pretrained-models",
	}
}

func sha256HexString(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}

func compareSemver(left string, right string) int {
	leftParts := parseSemverParts(left)
	rightParts := parseSemverParts(right)
	for index := 0; index < 3; index++ {
		switch {
		case leftParts[index] < rightParts[index]:
			return -1
		case leftParts[index] > rightParts[index]:
			return 1
		}
	}
	return 0
}

func parseSemverParts(raw string) [3]int {
	normalized := strings.TrimPrefix(strings.TrimSpace(raw), "v")
	segments := strings.SplitN(normalized, "-", 2)
	values := strings.Split(segments[0], ".")
	var parsed [3]int
	for index := 0; index < len(parsed) && index < len(values); index++ {
		value, err := strconv.Atoi(values[index])
		if err == nil {
			parsed[index] = value
		}
	}
	return parsed
}
