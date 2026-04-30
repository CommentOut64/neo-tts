package bootstrap

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

func TestAssessStartupGPUCompatibilityIsSilentForSupportedCU128Driver(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cu128-v1"}}},
		NvidiaGPUProbeResult{
			GPUs: []NvidiaGPUInfo{
				{Name: "NVIDIA GeForce RTX 4090", DriverVersion: "528.33"},
			},
		},
	)

	if notice != nil {
		t.Fatalf("expected no notice, got %#v", notice)
	}
}

func TestAssessStartupGPUCompatibilityIsSilentForRuntimeCompatibleCU128Driver(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cu128-v1"}}},
		NvidiaGPUProbeResult{
			GPUs: []NvidiaGPUInfo{
				{Name: "NVIDIA GeForce RTX 4090", DriverVersion: "566.36"},
			},
		},
	)

	if notice != nil {
		t.Fatalf("expected no notice, got %#v", notice)
	}
}

func TestAssessStartupGPUCompatibilityWarns50SeriesCU128OldDriver(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cu128-v1"}}},
		NvidiaGPUProbeResult{
			GPUs: []NvidiaGPUInfo{
				{Name: "NVIDIA GeForce RTX 5090", DriverVersion: "528.32"},
			},
		},
	)

	if notice == nil {
		t.Fatal("expected notice")
	}
	if notice.Message != "检测到驱动版本过低，请先更新显卡驱动" {
		t.Fatalf("unexpected message: %q", notice.Message)
	}
}

func TestAssessStartupGPUCompatibilityWarnsNon50SeriesCU128OldDriver(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cu128-v1"}}},
		NvidiaGPUProbeResult{
			GPUs: []NvidiaGPUInfo{
				{Name: "NVIDIA GeForce RTX 4090", DriverVersion: "528.32"},
			},
		},
	)

	if notice == nil {
		t.Fatal("expected notice")
	}
	if notice.Message != "检测到驱动版本过低，请先更新显卡驱动或下载后缀为cu118的整合包" {
		t.Fatalf("unexpected message: %q", notice.Message)
	}
}

func TestAssessStartupGPUCompatibilityWarnsWhenProbeFails(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cu128-v1"}}},
		NvidiaGPUProbeResult{Err: errors.New("nvidia-smi timed out")},
	)

	if notice == nil {
		t.Fatal("expected notice")
	}
	if notice.Message != "无法检测显卡和驱动版本，请确认已安装 NVIDIA 显卡及可用驱动" {
		t.Fatalf("unexpected message: %q", notice.Message)
	}
}

func TestAssessStartupGPUCompatibilityIsSilentForUnknownRuntime(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cpu-v1"}}},
		NvidiaGPUProbeResult{Err: errors.New("nvidia-smi missing")},
	)

	if notice != nil {
		t.Fatalf("expected no notice for unknown runtime target, got %#v", notice)
	}
}

func TestAssessStartupGPUCompatibilityWarnsWhenNoNvidiaGPUIsReported(t *testing.T) {
	notice := AssessStartupGPUCompatibility(
		CurrentState{Packages: map[string]PackageState{"python-runtime": {Version: "py311-cu128-v1"}}},
		NvidiaGPUProbeResult{},
	)

	if notice == nil {
		t.Fatal("expected notice")
	}
	if notice.Message != "未检测到 NVIDIA 显卡，请确认设备具备 NVIDIA 显卡及可用驱动" {
		t.Fatalf("unexpected message: %q", notice.Message)
	}
}

func TestParseNvidiaSMIGPUQueryOutputParsesMultipleRows(t *testing.T) {
	gpus := ParseNvidiaSMIGPUQueryOutput("NVIDIA GeForce RTX 4090, 572.83\nNVIDIA GeForce RTX 5090, 566.36\n")

	if len(gpus) != 2 {
		t.Fatalf("expected 2 gpus, got %d", len(gpus))
	}
	if gpus[1].Name != "NVIDIA GeForce RTX 5090" || gpus[1].DriverVersion != "566.36" {
		t.Fatalf("unexpected second GPU: %#v", gpus[1])
	}
}

func TestIsNvidia50SeriesGPUDoesNotMisclassifyRTXA5000(t *testing.T) {
	if IsNvidia50SeriesGPU("NVIDIA RTX A5000") {
		t.Fatal("RTX A5000 must not be classified as GeForce RTX 50 series")
	}
	if !IsNvidia50SeriesGPU("NVIDIA GeForce RTX 5070 Ti") {
		t.Fatal("GeForce RTX 5070 Ti must be classified as 50 series")
	}
	if !IsNvidia50SeriesGPU("NVIDIA GeForce RTX 5090D") {
		t.Fatal("GeForce RTX 5090D must be classified as 50 series")
	}
	if IsNvidia50SeriesGPU("NVIDIA RTX 5000 Ada Generation") {
		t.Fatal("RTX 5000 Ada must not be classified as GeForce RTX 50 series")
	}
}

func TestStartupCompatibilityNoticeScriptShowsWarningMessage(t *testing.T) {
	script := startupCompatibilityNoticePowerShellScript("检测到驱动版本过低，请先更新显卡驱动")

	if !strings.Contains(script, "PresentationFramework") {
		t.Fatalf("script missing WPF assembly: %s", script)
	}
	if !strings.Contains(script, "NeoTTS 兼容性提醒") {
		t.Fatalf("script missing title: %s", script)
	}
	if !strings.Contains(script, "检测到驱动版本过低，请先更新显卡驱动") {
		t.Fatalf("script missing message: %s", script)
	}
}

func TestNewNvidiaSMIQueryCommandHidesWindow(t *testing.T) {
	command := newNvidiaSMIQueryCommand(context.Background())

	if command.SysProcAttr == nil || !command.SysProcAttr.HideWindow {
		t.Fatal("nvidia-smi command HideWindow = false, want true")
	}
}

func TestNewStartupCompatibilityNoticeCommandHidesWindow(t *testing.T) {
	command := newStartupCompatibilityNoticeCommand("检测到驱动版本过低，请先更新显卡驱动")

	if command.SysProcAttr == nil || !command.SysProcAttr.HideWindow {
		t.Fatal("startup compatibility notice command HideWindow = false, want true")
	}
}

func TestProbeNvidiaGPUWithTimeoutDoesNotRetryDeadline(t *testing.T) {
	attempts := 0
	result := probeNvidiaGPUWithTimeout(
		time.Millisecond,
		func(ctx context.Context) NvidiaGPUProbeResult {
			attempts++
			return NvidiaGPUProbeResult{Err: context.DeadlineExceeded}
		},
	)

	if !errors.Is(result.Err, context.DeadlineExceeded) {
		t.Fatalf("Err = %v, want context deadline exceeded", result.Err)
	}
	if attempts != 1 {
		t.Fatalf("attempts = %d, want 1", attempts)
	}
}
