package bootstrap

import (
	"context"
	"fmt"
	"net"
	"net/http"
)

type ControlServer struct {
	Origin string
	server *http.Server
	listen net.Listener
}

func StartControlServer(app *App) (*ControlServer, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	server := &http.Server{
		Handler: app.Handler(),
	}
	control := &ControlServer{
		Origin: fmt.Sprintf("http://%s", listener.Addr().String()),
		server: server,
		listen: listener,
	}
	go func() {
		_ = server.Serve(listener)
	}()
	return control, nil
}

func (server *ControlServer) Close(ctx context.Context) error {
	if server == nil || server.server == nil {
		return nil
	}
	return server.server.Shutdown(ctx)
}
