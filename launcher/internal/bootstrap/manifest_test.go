package bootstrap

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCheckForUpdateReturnsUpToDateWhenReleaseIDMatches(t *testing.T) {
	manifest := ReleaseManifest{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.1",
		Channel:       "stable",
		ReleaseKind:   "stable",
		NotesURL:      "https://cdn.example.com/notes/v0.0.1.md",
		Packages: map[string]RemotePackage{
			"shell": {Version: "v0.0.1", URL: "https://cdn.example.com/shell.zip", SHA256: "abc"},
		},
	}
	manifestBytes := mustJSON(t, manifest)
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/channels/stable/latest.json":
			_ = json.NewEncoder(w).Encode(ChannelLatest{
				SchemaVersion:       1,
				Channel:             "stable",
				EnableDevRelease:    false,
				ReleaseID:           "v0.0.1",
				ReleaseKind:         "stable",
				ManifestURL:         server.URL + "/releases/v0.0.1/manifest.json",
				ManifestSHA256:      sha256Hex(manifestBytes),
				MinBootstrapVersion: "1.1.0",
			})
		case "/releases/v0.0.1/manifest.json":
			_, _ = w.Write(manifestBytes)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	result, err := CheckForUpdate(
		context.Background(),
		UpdateCheckOptions{
			Client:              server.Client(),
			LatestURL:           server.URL + "/channels/stable/latest.json",
			CurrentState:        CurrentState{ReleaseID: "v0.0.1"},
			BootstrapVersion:    "1.1.0",
			AllowedPackageOrder: DefaultPackageOrder(),
		},
	)
	if err != nil {
		t.Fatalf("CheckForUpdate returned error: %v", err)
	}

	if result.Status != UpdateStatusUpToDate {
		t.Fatalf("Status = %q, want %q", result.Status, UpdateStatusUpToDate)
	}
}

func TestCheckForUpdateReturnsBootstrapUpgradeRequiredWhenMinBootstrapVersionIsHigher(t *testing.T) {
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/channels/stable/latest.json" {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(ChannelLatest{
			SchemaVersion:       1,
			Channel:             "stable",
			EnableDevRelease:    false,
			ReleaseID:           "v0.0.2",
			ReleaseKind:         "stable",
			ManifestURL:         server.URL + "/releases/v0.0.2/manifest.json",
			ManifestSHA256:      "unused",
			MinBootstrapVersion: "1.2.0",
		})
	}))
	defer server.Close()

	result, err := CheckForUpdate(
		context.Background(),
		UpdateCheckOptions{
			Client:              server.Client(),
			LatestURL:           server.URL + "/channels/stable/latest.json",
			CurrentState:        CurrentState{ReleaseID: "v0.0.1"},
			BootstrapVersion:    "1.1.0",
			AllowedPackageOrder: DefaultPackageOrder(),
		},
	)
	if err != nil {
		t.Fatalf("CheckForUpdate returned error: %v", err)
	}

	if result.Status != UpdateStatusBootstrapUpgradeRequired {
		t.Fatalf("Status = %q, want %q", result.Status, UpdateStatusBootstrapUpgradeRequired)
	}
	if result.MinBootstrapVersion != "1.2.0" {
		t.Fatalf("MinBootstrapVersion = %q, want %q", result.MinBootstrapVersion, "1.2.0")
	}
}

func TestCheckForUpdateComparesLayerVersionsAndReturnsChangedPackages(t *testing.T) {
	manifest := ReleaseManifest{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Channel:       "stable",
		ReleaseKind:   "stable",
		NotesURL:      "https://cdn.example.com/notes/v0.0.2.md",
		Packages: map[string]RemotePackage{
			"shell":              {Version: "v0.0.2", URL: "https://cdn.example.com/shell.zip", SHA256: "shell", SizeBytes: 100},
			"app-core":           {Version: "v0.0.2", URL: "https://cdn.example.com/app-core.zip", SHA256: "app-core", SizeBytes: 200},
			"runtime":            {Version: "py311-cu124-v1", URL: "https://cdn.example.com/runtime.zip", SHA256: "runtime", SizeBytes: 300},
			"models":             {Version: "builtin-v1", URL: "https://cdn.example.com/models.zip", SHA256: "models", SizeBytes: 400},
			"pretrained-models":  {Version: "support-v2", URL: "https://cdn.example.com/pretrained.zip", SHA256: "pretrained", SizeBytes: 500},
			"bootstrap":          {Version: "1.1.0", URL: "https://cdn.example.com/bootstrap.zip", SHA256: "bootstrap", SizeBytes: 10},
			"update-agent":       {Version: "1.1.0", URL: "https://cdn.example.com/update-agent.zip", SHA256: "agent", SizeBytes: 20},
		},
	}
	manifestBytes := mustJSON(t, manifest)
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/channels/stable/latest.json":
			_ = json.NewEncoder(w).Encode(ChannelLatest{
				SchemaVersion:       1,
				Channel:             "stable",
				EnableDevRelease:    false,
				ReleaseID:           "v0.0.2",
				ReleaseKind:         "stable",
				ManifestURL:         server.URL + "/releases/v0.0.2/manifest.json",
				ManifestSHA256:      sha256Hex(manifestBytes),
				MinBootstrapVersion: "1.1.0",
			})
		case "/releases/v0.0.2/manifest.json":
			_, _ = w.Write(manifestBytes)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	result, err := CheckForUpdate(
		context.Background(),
		UpdateCheckOptions{
			Client:   server.Client(),
			LatestURL: server.URL + "/channels/stable/latest.json",
			CurrentState: CurrentState{
				ReleaseID: "v0.0.1",
				Packages: map[string]PackageState{
					"shell":             {Version: "v0.0.1"},
					"app-core":          {Version: "v0.0.1"},
					"runtime":           {Version: "py311-cu124-v1"},
					"models":            {Version: "builtin-v1"},
					"pretrained-models": {Version: "support-v1"},
					"bootstrap":         {Version: "1.1.0"},
					"update-agent":      {Version: "1.1.0"},
				},
			},
			BootstrapVersion:    "1.1.0",
			AllowedPackageOrder: DefaultPackageOrder(),
		},
	)
	if err != nil {
		t.Fatalf("CheckForUpdate returned error: %v", err)
	}

	if result.Status != UpdateStatusUpdateAvailable {
		t.Fatalf("Status = %q, want %q", result.Status, UpdateStatusUpdateAvailable)
	}
	wantChanged := []string{"shell", "app-core", "pretrained-models"}
	if !equalStrings(result.ChangedPackages, wantChanged) {
		t.Fatalf("ChangedPackages = %#v, want %#v", result.ChangedPackages, wantChanged)
	}
	if result.EstimatedDownloadBytes != 800 {
		t.Fatalf("EstimatedDownloadBytes = %d, want %d", result.EstimatedDownloadBytes, 800)
	}
	if result.NotesURL != manifest.NotesURL {
		t.Fatalf("NotesURL = %q, want %q", result.NotesURL, manifest.NotesURL)
	}
}

func TestCheckForUpdateReturnsManifestIntegrityFailedWhenShaMismatch(t *testing.T) {
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/channels/stable/latest.json":
			_ = json.NewEncoder(w).Encode(ChannelLatest{
				SchemaVersion:       1,
				Channel:             "stable",
				EnableDevRelease:    false,
				ReleaseID:           "v0.0.2",
				ReleaseKind:         "stable",
				ManifestURL:         server.URL + "/releases/v0.0.2/manifest.json",
				ManifestSHA256:      "bad",
				MinBootstrapVersion: "1.1.0",
			})
		case "/releases/v0.0.2/manifest.json":
			_, _ = w.Write([]byte(`{"schemaVersion":1}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	_, err := CheckForUpdate(
		context.Background(),
		UpdateCheckOptions{
			Client:              server.Client(),
			LatestURL:           server.URL + "/channels/stable/latest.json",
			CurrentState:        CurrentState{ReleaseID: "v0.0.1"},
			BootstrapVersion:    "1.1.0",
			AllowedPackageOrder: DefaultPackageOrder(),
		},
	)
	if err == nil {
		t.Fatal("CheckForUpdate returned nil error, want manifest integrity error")
	}

	bootstrapErr, ok := err.(*BootstrapError)
	if !ok {
		t.Fatalf("error type = %T, want *BootstrapError", err)
	}
	if bootstrapErr.Code != ErrCodeManifestIntegrityFailed {
		t.Fatalf("Code = %q, want %q", bootstrapErr.Code, ErrCodeManifestIntegrityFailed)
	}
}

func mustJSON(t *testing.T, value any) []byte {
	t.Helper()
	payload, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("json.Marshal returned error: %v", err)
	}
	return payload
}

func sha256Hex(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}

func equalStrings(left []string, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}
