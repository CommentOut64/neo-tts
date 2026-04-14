package windows

import "testing"

func TestFindListeningPIDUsesNativeTableQuery(t *testing.T) {
	pid, err := findListeningPIDByPortFromRows(5175, []tcpRowOwnerPID{
		{LocalPort: encodeTCPPort(18600), OwningPID: 1111},
		{LocalPort: encodeTCPPort(5175), OwningPID: 2222},
	})
	if err != nil {
		t.Fatalf("findListeningPIDByPortFromRows returned error: %v", err)
	}
	if pid != 2222 {
		t.Fatalf("pid = %d, want 2222", pid)
	}
}

func TestFindListeningPIDReturnsZeroWhenPortMissing(t *testing.T) {
	pid, err := findListeningPIDByPortFromRows(9999, []tcpRowOwnerPID{
		{LocalPort: encodeTCPPort(5175), OwningPID: 2222},
	})
	if err != nil {
		t.Fatalf("findListeningPIDByPortFromRows returned error: %v", err)
	}
	if pid != 0 {
		t.Fatalf("pid = %d, want 0", pid)
	}
}

func encodeTCPPort(port int) uint32 {
	if port <= 0 {
		return 0
	}
	return uint32(byte(port>>8)) | uint32(byte(port&0xff))<<8
}
