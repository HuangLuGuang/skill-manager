package managedclient

import "testing"

func TestModelJSONNativeCommentsStringsAndTrailingCommas(t *testing.T) {
	var root map[string]any
	source := []byte(`{ // config
 url: 'https://example.com/a//b', /* preserve slash in value */
 message: 'a\'b', quoted: '\"hello\"', hex: 0x10, ratio: .5,
 nested: {enabled: true,}, list: [1,2,],
 }`)
	if err := decodeModelJSON(source, &root); err != nil {
		t.Fatal(err)
	}
	if root["url"] != "https://example.com/a//b" || root["message"] != "a'b" || root["hex"] != float64(16) || root["ratio"] != 0.5 {
		t.Fatalf("incorrect native JSON values: %+v", root)
	}
}

func TestModelJSONRejectsMalformedAndNonFiniteValues(t *testing.T) {
	for _, source := range []string{`{x:NaN}`, `{x:Infinity}`, `{/* missing`, "{x:'unterminated}", `null`, `[1,2]`, `{"x":1,,}`} {
		var root map[string]any
		if decodeModelJSON([]byte(source), &root) == nil {
			t.Fatalf("accepted invalid native config %q", source)
		}
	}
}
