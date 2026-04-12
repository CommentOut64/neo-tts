package windows

import "testing"

func TestIsCurrentProcessElevatedUsesNativeTokenCheck(t *testing.T) {
	previous := currentProcessElevatedFn
	defer func() {
		currentProcessElevatedFn = previous
	}()

	calls := 0
	currentProcessElevatedFn = func() (bool, error) {
		calls++
		return true, nil
	}

	elevated, err := IsCurrentProcessElevated()
	if err != nil {
		t.Fatalf("IsCurrentProcessElevated returned error: %v", err)
	}
	if !elevated {
		t.Fatal("Elevated = false, want true")
	}
	if calls != 1 {
		t.Fatalf("native token check calls = %d, want 1", calls)
	}
}
