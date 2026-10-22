package agentlog

import (
	"bytes"
	"context"
	"encoding/binary"
	"hash/crc32"
	"strings"
	"unicode/utf16"

	"github.com/golang/snappy"
)

func doubaoCRC(b []byte, want uint32) bool {
	x := crc32.Checksum(b, crc32.MakeTable(crc32.Castagnoli))
	return (x>>15|x<<17)+0xa282ead8 == want
}

func doubaoStateKey(k []byte) bool {
	if len(k) < 6 || k[0] != 0 || k[3] != 1 || k[4] != 1 {
		return false
	}
	n, size := binary.Uvarint(k[5:])
	if size <= 0 || n > 512 || 5+size+int(n)*2 != len(k) {
		return false
	}
	u := make([]uint16, int(n))
	for i := range u {
		u[i] = binary.BigEndian.Uint16(k[5+size+i*2:])
	}
	s := string(utf16.Decode(u))
	return strings.HasPrefix(s, "im-sdk:user:") && strings.HasSuffix(s, ":default-chat-im-protocol-store")
}

func doubaoUnwrap(v []byte) ([]byte, error) {
	_, n := binary.Uvarint(v)
	if n <= 0 {
		return nil, errDoubaoCache
	}
	v = v[n:]
	if bytes.HasPrefix(v, []byte{255, 17, 2}) {
		n, err := snappy.DecodedLen(v[3:])
		if err != nil || n > 8<<20 {
			return nil, errDoubaoCache
		}
		return snappy.Decode(nil, v[3:])
	}
	if len(v) > 8<<20 {
		return nil, errDoubaoCache
	}
	return v, nil
}

// Read committed WAL batches, including fragmented records. A live partial tail
// is retried on the next scan; checksums prevent treating torn writes as messages.
func doubaoWAL(ctx context.Context, b []byte, consume func([]byte, []byte) error) error {
	var pending []byte
	batch := func(v []byte) error {
		if len(v) < 12 {
			return errDoubaoCache
		}
		r := doubaoV8{b: v, i: 12}
		count := binary.LittleEndian.Uint32(v[8:])
		if count > 100000 {
			return errDoubaoCache
		}
		for j := uint32(0); j < count; j++ {
			t, e := r.take(1)
			if e != nil {
				return e
			}
			n, e := r.uint()
			if e != nil || n > uint64(len(v)) {
				return errDoubaoCache
			}
			k, e := r.take(int(n))
			if e != nil {
				return e
			}
			if t[0] == 0 {
				continue
			}
			if t[0] != 1 {
				return errDoubaoCache
			}
			n, e = r.uint()
			if e != nil || n > uint64(len(v)) {
				return errDoubaoCache
			}
			value, e := r.take(int(n))
			if e != nil {
				return e
			}
			if e = consume(k, value); e != nil {
				return e
			}
		}
		if r.i != len(v) {
			return errDoubaoCache
		}
		return nil
	}
	for i := 0; i+7 <= len(b); {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		remaining := 32768 - i%32768
		if remaining < 7 {
			i += remaining
			continue
		}
		n := int(binary.LittleEndian.Uint16(b[i+4:]))
		typ := b[i+6]
		if typ == 0 && n == 0 {
			i += remaining
			continue
		}
		if n+7 > remaining {
			return errDoubaoCache
		}
		if i+7+n > len(b) {
			break
		}
		if !doubaoCRC(b[i+6:i+7+n], binary.LittleEndian.Uint32(b[i:])) {
			return errDoubaoCache
		}
		v := b[i+7 : i+7+n]
		i += 7 + n
		switch typ {
		case 1:
			if len(pending) != 0 {
				return errDoubaoCache
			}
			if e := batch(v); e != nil {
				return e
			}
		case 2:
			if len(pending) != 0 {
				return errDoubaoCache
			}
			pending = append([]byte{}, v...)
		case 3, 4:
			if len(pending) == 0 {
				return errDoubaoCache
			}
			pending = append(pending, v...)
			if len(pending) > 16<<20 {
				return errDoubaoCache
			}
			if typ == 4 {
				if e := batch(pending); e != nil {
					return e
				}
				pending = nil
			}
		default:
			return errDoubaoCache
		}
	}
	return nil
}

func doubaoTable(ctx context.Context, b []byte, consume func([]byte, []byte) error) error {
	if len(b) < 48 || !bytes.Equal(b[len(b)-8:], []byte{0x57, 0xfb, 0x80, 0x8b, 0x24, 0x75, 0x47, 0xdb}) {
		return errDoubaoCache
	}
	block := func(off, size uint64) ([]byte, error) {
		if off > uint64(len(b)) || size > uint64(len(b))-off || uint64(len(b))-off-size < 5 {
			return nil, errDoubaoCache
		}
		v := b[off : off+size]
		typ := b[off+size]
		if !doubaoCRC(b[off:off+size+1], binary.LittleEndian.Uint32(b[off+size+1:])) {
			return nil, errDoubaoCache
		}
		if typ == 0 {
			return v, nil
		}
		if typ != 1 {
			return nil, errDoubaoCache
		}
		n, e := snappy.DecodedLen(v)
		if e != nil || n > 8<<20 {
			return nil, errDoubaoCache
		}
		return snappy.Decode(nil, v)
	}
	entries := func(raw []byte, fn func([]byte, []byte) error) error {
		if len(raw) < 4 {
			return errDoubaoCache
		}
		n := binary.LittleEndian.Uint32(raw[len(raw)-4:])
		if uint64(n)*4 > uint64(len(raw)-4) {
			return errDoubaoCache
		}
		r := doubaoV8{b: raw[:len(raw)-4-int(n)*4]}
		var key []byte
		for r.i < len(r.b) {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			shared, e := r.uint()
			if e != nil || shared > uint64(len(key)) {
				return errDoubaoCache
			}
			a, e := r.uint()
			if e != nil || a > uint64(len(raw)) {
				return errDoubaoCache
			}
			z, e := r.uint()
			if e != nil || z > uint64(len(raw)) {
				return errDoubaoCache
			}
			k, e := r.take(int(a))
			if e != nil {
				return e
			}
			key = append(append([]byte{}, key[:shared]...), k...)
			v, e := r.take(int(z))
			if e != nil {
				return e
			}
			if e = fn(key, v); e != nil {
				return e
			}
		}
		return nil
	}
	r := doubaoV8{b: b[len(b)-48 : len(b)-8]}
	for i := 0; i < 2; i++ {
		if _, e := r.uint(); e != nil {
			return e
		}
	}
	off, e := r.uint()
	if e != nil {
		return e
	}
	size, e := r.uint()
	if e != nil {
		return e
	}
	index, e := block(off, size)
	if e != nil {
		return e
	}
	return entries(index, func(_ []byte, h []byte) error {
		r := doubaoV8{b: h}
		off, e := r.uint()
		if e != nil {
			return e
		}
		size, e := r.uint()
		if e != nil {
			return e
		}
		raw, e := block(off, size)
		if e != nil {
			return e
		}
		return entries(raw, func(k, v []byte) error {
			if len(k) < 8 {
				return errDoubaoCache
			}
			if k[len(k)-8] != 1 {
				return nil
			}
			return consume(k[:len(k)-8], v)
		})
	})
}
