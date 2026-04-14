package supervisor

import "context"

type ownedProcessAttacherKey struct{}

func WithOwnedProcessAttacher(ctx context.Context, attach func(pid int) error) context.Context {
	if ctx == nil || attach == nil {
		return ctx
	}
	return context.WithValue(ctx, ownedProcessAttacherKey{}, attach)
}

func attachOwnedProcessFromContext(ctx context.Context) func(pid int) error {
	if ctx == nil {
		return nil
	}
	attach, _ := ctx.Value(ownedProcessAttacherKey{}).(func(pid int) error)
	return attach
}
