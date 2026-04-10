package web

import (
	"context"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestStaticServerFailsWhenDistMissing(t *testing.T) {
	_, err := StartStaticServer(Config{
		Host:    "127.0.0.1",
		Port:    0,
		DistDir: filepath.Join(t.TempDir(), "frontend", "dist"),
	})
	if err == nil {
		t.Fatal("StartStaticServer returned nil error, want missing dist failure")
	}
}

func TestStaticServerServesIndexFromConfiguredDir(t *testing.T) {
	projectRoot := t.TempDir()
	distDir := filepath.Join(projectRoot, "frontend", "dist")
	if err := os.MkdirAll(distDir, 0o755); err != nil {
		t.Fatalf("MkdirAll(%q): %v", distDir, err)
	}
	if err := os.WriteFile(filepath.Join(distDir, "index.html"), []byte("<html>launcher</html>"), 0o644); err != nil {
		t.Fatalf("WriteFile(index.html): %v", err)
	}

	server, err := StartStaticServer(Config{
		Host:    "127.0.0.1",
		Port:    0,
		DistDir: distDir,
	})
	if err != nil {
		t.Fatalf("StartStaticServer returned error: %v", err)
	}
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = server.Stop(shutdownCtx)
	}()

	resp, err := http.Get(server.Origin + "/")
	if err != nil {
		t.Fatalf("GET / returned error: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("ReadAll returned error: %v", err)
	}
	if !strings.Contains(string(body), "launcher") {
		t.Fatalf("response body = %q, want launcher", string(body))
	}
}
