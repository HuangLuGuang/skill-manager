package agentlog

import (
	"encoding/binary"
	"errors"
	"math"
	"strconv"
	"unicode/utf16"
)

// The persisted IM state contains plain V8 objects, arrays and scalar values.
// Unsupported host objects fail decoding instead of searching their bytes for messages.
type doubaoV8 struct {
	b        []byte
	i, nodes int
	refs     []any
}

var errDoubaoCache = errors.New("aidr_log_schema_unsupported")

func (r *doubaoV8) take(n int) ([]byte, error) {
	if n < 0 || n > len(r.b)-r.i {
		return nil, errDoubaoCache
	}
	b := r.b[r.i : r.i+n]
	r.i += n
	return b, nil
}

func (r *doubaoV8) uint() (uint64, error) {
	x, n := binary.Uvarint(r.b[r.i:])
	if n <= 0 {
		return 0, errDoubaoCache
	}
	r.i += n
	return x, nil
}

func (r *doubaoV8) value(depth int) (any, error) {
	r.nodes++
	if depth > 80 || r.nodes > 200000 {
		return nil, errDoubaoCache
	}
	for r.i < len(r.b) && r.b[r.i] == 0 {
		r.i++
	}
	t, err := r.take(1)
	if err != nil {
		return nil, err
	}
	switch t[0] {
	case '_', '-', '0':
		return nil, nil
	case 'T':
		return true, nil
	case 'F':
		return false, nil
	case 'I', 'U', '^':
		n, err := r.uint()
		if err != nil {
			return nil, err
		}
		if t[0] == '^' {
			if n >= uint64(len(r.refs)) {
				return nil, errDoubaoCache
			}
			return r.refs[n], nil
		}
		if t[0] == 'I' {
			return float64(int64(n>>1) ^ -int64(n&1)), nil
		}
		return float64(n), nil
	case 'N':
		b, err := r.take(8)
		if err != nil {
			return nil, err
		}
		return math.Float64frombits(binary.LittleEndian.Uint64(b)), nil
	case '"', 'S', 'c':
		n, err := r.uint()
		if err != nil || n > 8<<20 {
			return nil, errDoubaoCache
		}
		b, err := r.take(int(n))
		if err != nil {
			return nil, err
		}
		if t[0] == 'c' {
			if len(b)%2 != 0 {
				return nil, errDoubaoCache
			}
			u := make([]uint16, len(b)/2)
			for i := range u {
				u[i] = binary.LittleEndian.Uint16(b[i*2:])
			}
			return string(utf16.Decode(u)), nil
		}
		if t[0] == '"' {
			u := make([]rune, len(b))
			for i, v := range b {
				u[i] = rune(v)
			}
			return string(u), nil
		}
		return string(b), nil
	case 'o', 'a', 'A':
		m := map[string]any{}
		r.refs = append(r.refs, m)
		var length uint64
		if t[0] != 'o' {
			length, err = r.uint()
			if err != nil || length > 100000 {
				return nil, errDoubaoCache
			}
		}
		if t[0] == 'A' {
			for i := uint64(0); i < length; i++ {
				v, e := r.value(depth + 1)
				if e != nil {
					return nil, e
				}
				m[strconv.FormatUint(i, 10)] = v
			}
		}
		end := byte('{')
		if t[0] == 'a' {
			end = '@'
		}
		if t[0] == 'A' {
			end = '$'
		}
		var count uint64
		for {
			if r.i >= len(r.b) {
				return nil, errDoubaoCache
			}
			if r.b[r.i] == end {
				r.i++
				break
			}
			k, e := r.value(depth + 1)
			if e != nil {
				return nil, e
			}
			v, e := r.value(depth + 1)
			if e != nil {
				return nil, e
			}
			var key string
			switch k := k.(type) {
			case string:
				key = k
			case float64:
				key = strconv.FormatFloat(k, 'f', -1, 64)
			default:
				return nil, errDoubaoCache
			}
			m[key] = v
			count++
		}
		n, e := r.uint()
		if e != nil || n != count {
			return nil, errDoubaoCache
		}
		if t[0] != 'o' {
			n, e = r.uint()
			if e != nil || n != length {
				return nil, errDoubaoCache
			}
		}
		return m, nil
	default:
		return nil, errDoubaoCache
	}
}

func decodeDoubaoV8(b []byte) (map[string]any, error) {
	// Blink v21 envelope includes its fixed trailer-offset header before V8 v15.
	if len(b) < 17 || b[0] != 255 || b[1] != 21 || b[2] != 254 || b[15] != 255 || b[16] != 15 {
		return nil, errDoubaoCache
	}
	r := doubaoV8{b: b, i: 17}
	v, err := r.value(0)
	if err != nil {
		return nil, err
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, errDoubaoCache
	}
	return m, nil
}
