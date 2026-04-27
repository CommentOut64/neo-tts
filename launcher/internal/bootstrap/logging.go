package bootstrap

import (
	"encoding/json"
	"fmt"
	"time"
)

type LogEntry struct {
	Timestamp string         `json:"timestamp"`
	Level     string         `json:"level"`
	Component string         `json:"component"`
	Message   string         `json:"message"`
	Fields    map[string]any `json:"fields,omitempty"`
}

func FormatLogEntry(level string, component string, message string, fields map[string]any) string {
	payload, _ := json.Marshal(LogEntry{
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Level:     level,
		Component: component,
		Message:   message,
		Fields:    fields,
	})
	return fmt.Sprintf("%s\n", payload)
}
