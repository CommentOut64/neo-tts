package control

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

type Session struct {
	ID            string
	ControlOrigin string
	ControlToken  string
}

func newSession(controlOrigin string) (Session, error) {
	id, err := randomHex(16)
	if err != nil {
		return Session{}, err
	}
	token, err := randomHex(32)
	if err != nil {
		return Session{}, err
	}

	return Session{
		ID:            id,
		ControlOrigin: controlOrigin,
		ControlToken:  token,
	}, nil
}

func randomHex(size int) (string, error) {
	if size <= 0 {
		return "", fmt.Errorf("invalid random size: %d", size)
	}

	buffer := make([]byte, size)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return hex.EncodeToString(buffer), nil
}
