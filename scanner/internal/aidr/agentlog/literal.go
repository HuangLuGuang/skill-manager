package agentlog

import (
	"encoding/json"
	"errors"
	"strings"
)

// literalJSON accepts a small, non-executing subset of JavaScript literals.
// Expressions, interpolation, spreads, computed keys and duplicate keys fail.
func literalJSON(code string) (json.RawMessage, int, error) {
	p := literalParser{s: code}
	value, err := p.value(0)
	if err != nil {
		return nil, 0, err
	}
	raw, err := json.Marshal(value)
	return raw, p.i, err
}

type literalParser struct {
	s string
	i int
}

var errLiteral = errors.New("aidr_log_nonliteral_arguments")

func (p *literalParser) space() {
	for p.i < len(p.s) && strings.ContainsRune(" \r\n\t", rune(p.s[p.i])) {
		p.i++
	}
}
func (p *literalParser) str() (string, error) {
	quote := p.s[p.i]
	p.i++
	var b strings.Builder
	for p.i < len(p.s) {
		c := p.s[p.i]
		p.i++
		if c == quote {
			return b.String(), nil
		}
		if c == '$' && quote == '`' && p.i < len(p.s) && p.s[p.i] == '{' {
			return "", errLiteral
		}
		if c == '\\' {
			if p.i == len(p.s) {
				return "", errLiteral
			}
			c = p.s[p.i]
			p.i++
			switch c {
			case 'n':
				c = '\n'
			case 'r':
				c = '\r'
			case 't':
				c = '\t'
			case '\\', '\'', '"', '`', '/':
			default:
				return "", errLiteral
			}
		}
		b.WriteByte(c)
	}
	return "", errLiteral
}
func (p *literalParser) value(depth int) (any, error) {
	p.space()
	if depth > 16 || p.i >= len(p.s) {
		return nil, errLiteral
	}
	switch p.s[p.i] {
	case '\'', '"', '`':
		if p.s[p.i] == '"' {
			dec := json.NewDecoder(strings.NewReader(p.s[p.i:]))
			var s string
			if dec.Decode(&s) == nil {
				p.i += int(dec.InputOffset())
				return s, nil
			}
		}
		return p.str()
	case '{':
		p.i++
		obj := map[string]any{}
		p.space()
		if p.i < len(p.s) && p.s[p.i] == '}' {
			p.i++
			return obj, nil
		}
		for len(obj) < 64 {
			p.space()
			if p.i >= len(p.s) {
				return nil, errLiteral
			}
			var key string
			if p.s[p.i] == '\'' || p.s[p.i] == '"' {
				v, e := p.value(depth + 1)
				if e != nil {
					return nil, e
				}
				key = v.(string)
			} else {
				start := p.i
				for p.i < len(p.s) && strings.ContainsRune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$", rune(p.s[p.i])) {
					p.i++
				}
				if p.i == start {
					return nil, errLiteral
				}
				key = p.s[start:p.i]
			}
			if _, ok := obj[key]; ok {
				return nil, errLiteral
			}
			p.space()
			if p.i >= len(p.s) || p.s[p.i] != ':' {
				return nil, errLiteral
			}
			p.i++
			v, e := p.value(depth + 1)
			if e != nil {
				return nil, e
			}
			obj[key] = v
			p.space()
			if p.i >= len(p.s) {
				return nil, errLiteral
			}
			if p.s[p.i] == '}' {
				p.i++
				return obj, nil
			}
			if p.s[p.i] != ',' {
				return nil, errLiteral
			}
			p.i++
			p.space()
			if p.i < len(p.s) && p.s[p.i] == '}' {
				p.i++
				return obj, nil
			}
		}
		return nil, errLiteral
	default:
		dec := json.NewDecoder(strings.NewReader(p.s[p.i:]))
		dec.UseNumber()
		var v any
		if dec.Decode(&v) != nil {
			return nil, errLiteral
		}
		switch v.(type) {
		case bool, json.Number, nil:
			p.i += int(dec.InputOffset())
			return v, nil
		}
		return nil, errLiteral
	}
}
