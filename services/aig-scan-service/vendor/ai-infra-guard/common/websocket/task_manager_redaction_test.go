// Copyright (c) 2024-2026 Tencent Zhuque Lab. All rights reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package websocket

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/Tencent/AI-Infra-Guard/common/agent"
)

func TestRedactTaskParamsHandlesTypedNestedSlices(t *testing.T) {
	params := map[string]interface{}{
		"model": []agent.ModelParams{
			{BaseUrl: "https://target.example/v1", Token: "target-secret", Model: "target"},
		},
		"eval_model": agent.ModelParams{
			BaseUrl: "https://evaluator.example/v1",
			Token:   "evaluator-secret",
			Model:   "evaluator",
		},
	}

	encoded, err := json.Marshal(redactTaskParams(params))
	if err != nil {
		t.Fatalf("marshal redacted params: %v", err)
	}
	text := string(encoded)
	if strings.Contains(text, "target-secret") || strings.Contains(text, "evaluator-secret") {
		t.Fatalf("typed nested credentials were persisted: %s", text)
	}
	if strings.Count(text, "[REDACTED]") != 2 {
		t.Fatalf("expected two redacted credentials, got %s", text)
	}
}
