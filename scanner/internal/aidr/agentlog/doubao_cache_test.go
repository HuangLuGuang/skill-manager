package agentlog

import (
	"bytes"
	"context"
	"encoding/binary"
	"hash/crc32"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unicode/utf16"

	"github.com/golang/snappy"
)

func doubaoTestWAL(t *testing.T, corrupt bool) []byte {
	t.Helper()
	raw, err := os.ReadFile("testdata/doubao-cache.bin")
	if err != nil {
		t.Fatal(err)
	}
	key := []byte{0, 1, 1, 1, 1}
	name := utf16.Encode([]rune("im-sdk:user:123:default-chat-im-protocol-store"))
	key = binary.AppendUvarint(key, uint64(len(name)))
	for _, v := range name {
		key = binary.BigEndian.AppendUint16(key, v)
	}
	value := append([]byte{1, 255, 17, 2}, snappy.Encode(nil, raw)...)
	batch := make([]byte, 12)
	binary.LittleEndian.PutUint32(batch[8:], 1)
	batch = append(batch, 1)
	batch = binary.AppendUvarint(batch, uint64(len(key)))
	batch = append(batch, key...)
	batch = binary.AppendUvarint(batch, uint64(len(value)))
	batch = append(batch, value...)
	record := make([]byte, 7)
	binary.LittleEndian.PutUint16(record[4:], uint16(len(batch)))
	record[6] = 1
	record = append(record, batch...)
	crc := crc32.Checksum(record[6:], crc32.MakeTable(crc32.Castagnoli))
	binary.LittleEndian.PutUint32(record, (crc>>15|crc<<17)+0xa282ead8)
	if corrupt {
		record[len(record)-1] ^= 1
	}
	return record
}

func TestDoubaoCacheImmutableMessages(t *testing.T) {
	raw, _ := os.ReadFile("testdata/doubao-cache.bin")
	r := doubaoV8{b: raw, i: 17}
	if _, e := r.value(0); e != nil {
		t.Fatalf("fixture offset %d: %v", r.i, e)
	}
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(base, "IndexedDB")
	for _, dir := range []string{doubaoChatDB, doubaoLauncherDB} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0700); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(root, doubaoChatDB, "CURRENT")
	os.WriteFile(path, []byte("MANIFEST-000001\n"), 0600)
	wal := doubaoTestWAL(t, false)
	if e := doubaoWAL(context.Background(), wal, func(k, v []byte) error {
		if !doubaoStateKey(k) {
			t.Fatal("state key rejected")
		}
		raw, e := doubaoUnwrap(v)
		if e != nil {
			t.Fatal("unwrap", e)
		}
		_, e = decodeDoubaoV8(raw)
		if e != nil {
			t.Fatal("decode", e)
		}
		return e
	}); e != nil {
		t.Fatal("wal", e)
	}
	os.WriteFile(filepath.Join(root, doubaoChatDB, "000001.log"), wal, 0600)
	// The second WebView retains the same native messages; they must not duplicate.
	os.WriteFile(filepath.Join(root, doubaoLauncherDB, "000001.log"), wal, 0600)
	rows, err := doubaoCacheSnapshot(context.Background(), root)
	if err != nil || len(rows) != 4 {
		t.Fatalf("rows=%d err=%v", len(rows), err)
	}
	for _, m := range rows {
		if strings.Contains(m.Text, "unfinished") || strings.Contains(m.Text, "hidden") {
			t.Fatal("mutable/hidden body collected")
		}
		if m.ID == "2001:done" && m.Turn != "1001" {
			t.Fatal(m)
		}
		if m.ID == "2002:orphan" && m.Turn != "" {
			t.Fatal(m)
		}
	}
	s, err := NewSource("doubaowork", root, path)
	if err != nil {
		t.Fatal(err)
	}
	p := AuditPolicy{Version: "7", Receipt: strings.Repeat("a", 32), MessageSchema: 1, Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	b := DefaultBudget()
	b.Events = 2
	since := time.UnixMilli(1792638450000)
	first, err := ReadWithPolicy(context.Background(), s, Cursor{}, b, since, &p)
	if err != nil || len(first.Events) != 2 || first.Cursor.ScanComplete {
		t.Fatalf("first %+v %v", first, err)
	}
	second, err := ReadWithPolicy(context.Background(), s, first.Cursor, b, since, &p)
	if err != nil || len(second.Events) != 2 || !second.Cursor.ScanComplete {
		t.Fatalf("second %+v %v", second, err)
	}
	for _, e := range append(first.Events, second.Events...) {
		if err := ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
		if e.ObservedAtSource != "" {
			t.Fatal("cache timestamp lost")
		}
	}
	third, err := ReadWithPolicy(context.Background(), s, second.Cursor, b, since, &p)
	if err != nil || len(third.Events) != 0 {
		t.Fatal("replay duplicated", err)
	}
	p.Capture.Prompt = false
	out, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), since, &p)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range out.Events {
		if e.Kind == "user_message" && len(e.Message.Contents) != 0 {
			t.Fatal("prompt switch ignored")
		}
	}
	p.Lifecycle = &AuditLifecycle{Enabled: false, RetentionDays: 7}
	out, err = ReadWithPolicy(context.Background(), s, Cursor{}, b, since, &p)
	if err != nil || len(out.Events) != 0 {
		t.Fatal("collection switch ignored")
	}
}

func TestDoubaoCacheCorruptAndPartialWAL(t *testing.T) {
	count := 0
	fn := func(k, v []byte) error { count++; return nil }
	if err := doubaoWAL(context.Background(), doubaoTestWAL(t, true), fn); err == nil || count != 0 {
		t.Fatal("bad CRC accepted")
	}
	raw := doubaoTestWAL(t, false)
	if err := doubaoWAL(context.Background(), raw[:len(raw)-1], fn); err != nil || count != 0 {
		t.Fatal("partial tail accepted", err)
	}
	if err := doubaoWAL(context.Background(), bytes.Repeat([]byte{255}, 7), fn); err == nil {
		t.Fatal("bad length accepted")
	}
	if _, err := decodeDoubaoV8([]byte{255, 15}); err == nil {
		t.Fatal("unsupported envelope accepted")
	}
}

func TestDoubaoCacheTableAndFragments(t *testing.T) {
	wal := doubaoTestWAL(t, false)
	var key, value []byte
	if e := doubaoWAL(context.Background(), wal, func(k, v []byte) error { key = append([]byte{}, k...); value = append([]byte{}, v...); return nil }); e != nil {
		t.Fatal(e)
	}
	block := func(k, v []byte) []byte {
		b := binary.AppendUvarint(nil, 0)
		b = binary.AppendUvarint(b, uint64(len(k)))
		b = binary.AppendUvarint(b, uint64(len(v)))
		b = append(b, k...)
		b = append(b, v...)
		b = binary.LittleEndian.AppendUint32(b, 0)
		return binary.LittleEndian.AppendUint32(b, 1)
	}
	trailer := func(b []byte) []byte {
		b = append(b, 0)
		x := crc32.Checksum(b, crc32.MakeTable(crc32.Castagnoli))
		return binary.LittleEndian.AppendUint32(b, (x>>15|x<<17)+0xa282ead8)
	}
	internal := append(append([]byte{}, key...), 1, 0, 0, 0, 0, 0, 0, 0)
	data := block(internal, value)
	file := trailer(data)
	handle := binary.AppendUvarint(nil, 0)
	handle = binary.AppendUvarint(handle, uint64(len(data)))
	index := block(internal, handle)
	off := len(file)
	file = append(file, trailer(index)...)
	footer := []byte{0, 0}
	footer = binary.AppendUvarint(footer, uint64(off))
	footer = binary.AppendUvarint(footer, uint64(len(index)))
	footer = append(footer, make([]byte, 40-len(footer))...)
	footer = append(footer, 0x57, 0xfb, 0x80, 0x8b, 0x24, 0x75, 0x47, 0xdb)
	file = append(file, footer...)
	n := 0
	consume := func(k, v []byte) error {
		n++
		if !bytes.Equal(k, key) || !bytes.Equal(v, value) {
			t.Fatal("wrong decoded table value")
		}
		return nil
	}
	if e := doubaoTable(context.Background(), file, consume); e != nil || n != 1 {
		t.Fatal("table", e, n)
	}
	file[2] ^= 1
	if e := doubaoTable(context.Background(), file, consume); e == nil {
		t.Fatal("table CRC ignored")
	}
	frame := func(typ byte, body []byte) []byte {
		b := make([]byte, 7)
		binary.LittleEndian.PutUint16(b[4:], uint16(len(body)))
		b[6] = typ
		b = append(b, body...)
		x := crc32.Checksum(b[6:], crc32.MakeTable(crc32.Castagnoli))
		binary.LittleEndian.PutUint32(b, (x>>15|x<<17)+0xa282ead8)
		return b
	}
	payload := wal[7:]
	split := len(payload) / 2
	fragmented := append(frame(2, payload[:split]), frame(4, payload[split:])...)
	n = 0
	if e := doubaoWAL(context.Background(), fragmented, consume); e != nil || n != 1 {
		t.Fatal("fragments", e, n)
	}
}

func TestDoubaoCacheLive(t *testing.T) {
	root := os.Getenv("DOUBAO_CACHE_ROOT")
	if root == "" {
		t.Skip("explicit local cache path required")
	}
	rows, err := doubaoCacheSnapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	for _, m := range rows {
		counts[m.Role]++
		if m.Session == "38448709502340354" {
			t.Log(m.Role, m.ID, m.Turn, len(m.Text))
		}
	}
	t.Log("retained immutable messages", counts)
}
