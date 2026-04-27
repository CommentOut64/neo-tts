package bootstrap

import (
	"context"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	cuda128MinimumDriverVersion = "570.65"
	cuda118MinimumDriverVersion = "522.06"
)

var geForceRTX50SeriesPattern = regexp.MustCompile(`(?i)\bgeforce\s+rtx\s+50(50|60|70|80|90)[a-z]?\b|\brtx\s+50(50|60|70|80|90)[a-z]?\b`)

type NvidiaGPUInfo struct {
	Name          string
	DriverVersion string
}

type NvidiaGPUProbeResult struct {
	GPUs []NvidiaGPUInfo
	Err  error
}

type StartupGPUCompatibilityNotice struct {
	Message string
	Reason  string
}

func ProbeNvidiaGPUWithTimeout(timeout time.Duration) NvidiaGPUProbeResult {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return ProbeNvidiaGPU(ctx)
}

func ProbeNvidiaGPU(ctx context.Context) NvidiaGPUProbeResult {
	command := exec.CommandContext(
		ctx,
		"nvidia-smi",
		"--query-gpu=name,driver_version",
		"--format=csv,noheader",
	)
	output, err := command.CombinedOutput()
	if ctx.Err() != nil {
		return NvidiaGPUProbeResult{Err: ctx.Err()}
	}
	if err != nil {
		if isNvidiaSMINoDeviceOutput(string(output)) {
			return NvidiaGPUProbeResult{}
		}
		return NvidiaGPUProbeResult{Err: err}
	}
	gpus := ParseNvidiaSMIGPUQueryOutput(string(output))
	return NvidiaGPUProbeResult{GPUs: gpus}
}

func isNvidiaSMINoDeviceOutput(output string) bool {
	normalized := strings.ToLower(output)
	return strings.Contains(normalized, "no devices were found") ||
		strings.Contains(normalized, "couldn't find any nvidia devices") ||
		strings.Contains(normalized, "could not find any nvidia devices")
}

func ParseNvidiaSMIGPUQueryOutput(output string) []NvidiaGPUInfo {
	lines := strings.Split(output, "\n")
	gpus := make([]NvidiaGPUInfo, 0, len(lines))
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		parts := strings.Split(trimmed, ",")
		if len(parts) < 2 {
			continue
		}
		name := strings.TrimSpace(parts[0])
		driverVersion := strings.TrimSpace(parts[1])
		if name == "" || driverVersion == "" {
			continue
		}
		gpus = append(gpus, NvidiaGPUInfo{
			Name:          name,
			DriverVersion: driverVersion,
		})
	}
	return gpus
}

func AssessStartupGPUCompatibility(
	current CurrentState,
	probe NvidiaGPUProbeResult,
) *StartupGPUCompatibilityNotice {
	target, ok := resolveRuntimeDriverTarget(current)
	if !ok {
		return nil
	}
	if probe.Err != nil {
		return &StartupGPUCompatibilityNotice{
			Reason:  "gpu-probe-failed",
			Message: "无法检测显卡和驱动版本，请确认已安装 NVIDIA 显卡及可用驱动",
		}
	}
	if len(probe.GPUs) == 0 {
		return &StartupGPUCompatibilityNotice{
			Reason:  "nvidia-gpu-not-found",
			Message: "未检测到 NVIDIA 显卡，请确认设备具备 NVIDIA 显卡及可用驱动",
		}
	}

	for _, gpu := range probe.GPUs {
		if compareNvidiaDriverVersion(gpu.DriverVersion, target.minimumDriverVersion) >= 0 {
			return nil
		}
	}

	if target.cudaTag == "cu128" && !probeHas50SeriesGPU(probe) {
		return &StartupGPUCompatibilityNotice{
			Reason:  "cu128-driver-too-old-non-50-series",
			Message: "检测到驱动版本过低，请先更新显卡驱动或下载后缀为cu118的整合包",
		}
	}
	return &StartupGPUCompatibilityNotice{
		Reason:  target.cudaTag + "-driver-too-old",
		Message: "检测到驱动版本过低，请先更新显卡驱动",
	}
}

func IsNvidia50SeriesGPU(name string) bool {
	return geForceRTX50SeriesPattern.MatchString(name)
}

type runtimeDriverTarget struct {
	cudaTag              string
	minimumDriverVersion string
}

func resolveRuntimeDriverTarget(current CurrentState) (runtimeDriverTarget, bool) {
	runtimePackage, ok := current.Packages["runtime"]
	if !ok {
		return runtimeDriverTarget{}, false
	}
	version := strings.ToLower(strings.TrimSpace(runtimePackage.Version))
	switch {
	case strings.Contains(version, "cu128"):
		return runtimeDriverTarget{cudaTag: "cu128", minimumDriverVersion: cuda128MinimumDriverVersion}, true
	case strings.Contains(version, "cu118"):
		return runtimeDriverTarget{cudaTag: "cu118", minimumDriverVersion: cuda118MinimumDriverVersion}, true
	default:
		return runtimeDriverTarget{}, false
	}
}

func probeHas50SeriesGPU(probe NvidiaGPUProbeResult) bool {
	for _, gpu := range probe.GPUs {
		if IsNvidia50SeriesGPU(gpu.Name) {
			return true
		}
	}
	return false
}

func compareNvidiaDriverVersion(left string, right string) int {
	leftVersion := parseNvidiaDriverVersion(left)
	rightVersion := parseNvidiaDriverVersion(right)
	for index := 0; index < len(leftVersion); index++ {
		switch {
		case leftVersion[index] < rightVersion[index]:
			return -1
		case leftVersion[index] > rightVersion[index]:
			return 1
		}
	}
	return 0
}

func parseNvidiaDriverVersion(raw string) [3]int {
	var parsed [3]int
	fields := strings.Split(strings.TrimSpace(raw), ".")
	for index := 0; index < len(parsed) && index < len(fields); index++ {
		value, err := strconv.Atoi(strings.TrimSpace(fields[index]))
		if err != nil {
			break
		}
		parsed[index] = value
	}
	return parsed
}
