package web

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
)

const DefaultStaticServerPort = 15175

type Config struct {
	Host    string
	Port    int
	DistDir string
}

type StaticServer struct {
	server   *http.Server
	listener net.Listener
	Origin   string
	Port     int
}

func StartStaticServer(cfg Config) (*StaticServer, error) {
	if cfg.Host == "" {
		cfg.Host = "127.0.0.1"
	}
	if cfg.Port < 0 {
		return nil, errors.New("static server port must be non-negative")
	}

	info, err := os.Stat(cfg.DistDir)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("dist path is not a directory: %s", cfg.DistDir)
	}
	indexPath := filepath.Join(cfg.DistDir, "index.html")
	if _, err := os.Stat(indexPath); err != nil {
		return nil, err
	}

	listener, err := net.Listen("tcp", fmt.Sprintf("%s:%d", cfg.Host, cfg.Port))
	if err != nil {
		return nil, err
	}

	fileServer := http.FileServer(http.Dir(cfg.DistDir))
	server := &http.Server{
		Handler: fileServer,
	}
	go func() {
		_ = server.Serve(listener)
	}()

	tcpAddr, ok := listener.Addr().(*net.TCPAddr)
	if !ok {
		_ = listener.Close()
		return nil, errors.New("static server listener is not TCP")
	}

	return &StaticServer{
		server:   server,
		listener: listener,
		Origin:   fmt.Sprintf("http://%s:%d", cfg.Host, tcpAddr.Port),
		Port:     tcpAddr.Port,
	}, nil
}

func (server *StaticServer) Stop(ctx context.Context) error {
	if server == nil {
		return nil
	}
	return server.server.Shutdown(ctx)
}
