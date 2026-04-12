package control

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"strings"
	"sync"
)

type ServerOptions struct {
	Address    string
	OnShutdown func()
}

type ShutdownResponse struct {
	Accepted bool `json:"accepted"`
}

type Server struct {
	session      Session
	listener     net.Listener
	httpServer   *http.Server
	onShutdown   func()
	shutdownOnce sync.Once
	closeOnce    sync.Once
}

func StartServer(ctx context.Context, opts ServerOptions) (*Server, error) {
	address := opts.Address
	if strings.TrimSpace(address) == "" {
		address = "127.0.0.1:0"
	}

	listener, err := net.Listen("tcp", address)
	if err != nil {
		return nil, err
	}

	session, err := newSession("http://" + listener.Addr().String())
	if err != nil {
		_ = listener.Close()
		return nil, err
	}

	server := &Server{
		session:    session,
		listener:   listener,
		onShutdown: opts.OnShutdown,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/control/shutdown", server.handleShutdown)
	server.httpServer = &http.Server{
		BaseContext: func(net.Listener) context.Context {
			return ctx
		},
		Handler: mux,
	}

	go func() {
		<-ctx.Done()
		_ = server.Close()
	}()
	go func() {
		err := server.httpServer.Serve(listener)
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			_ = server.Close()
		}
	}()

	return server, nil
}

func (s *Server) Session() Session {
	if s == nil {
		return Session{}
	}
	return s.session
}

func (s *Server) Close() error {
	if s == nil {
		return nil
	}

	var closeErr error
	s.closeOnce.Do(func() {
		closeErr = s.httpServer.Close()
	})
	return closeErr
}

func (s *Server) handleShutdown(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		http.Error(writer, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if !isLoopbackRequest(request.RemoteAddr) {
		http.Error(writer, http.StatusText(http.StatusForbidden), http.StatusForbidden)
		return
	}
	if !hasBearerToken(request, s.session.ControlToken) {
		http.Error(writer, http.StatusText(http.StatusUnauthorized), http.StatusUnauthorized)
		return
	}

	accepted := false
	s.shutdownOnce.Do(func() {
		accepted = true
		if s.onShutdown != nil {
			s.onShutdown()
		}
	})

	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(http.StatusAccepted)
	_ = json.NewEncoder(writer).Encode(ShutdownResponse{Accepted: accepted})
}

func hasBearerToken(request *http.Request, expected string) bool {
	if request == nil || expected == "" {
		return false
	}
	authorization := strings.TrimSpace(request.Header.Get("Authorization"))
	if !strings.HasPrefix(authorization, "Bearer ") {
		return false
	}
	return strings.TrimPrefix(authorization, "Bearer ") == expected
}

func isLoopbackRequest(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		return false
	}
	ip := net.ParseIP(host)
	if ip != nil {
		return ip.IsLoopback()
	}
	return strings.EqualFold(host, "localhost")
}
