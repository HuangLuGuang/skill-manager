package main

// A prerequisite report is separate from an applied channel observation.
// It never asserts ES authorization, subscription or a running collector.
type systemPrerequisites struct {
	Version         int                    `json:"version"`
	Code            string                 `json:"code"`
	CheckedAt       string                 `json:"checked_at"`
	Components      []systemComponentCheck `json:"components"`
	ESAuthorization string                 `json:"es_authorization"`
	ESSubscription  string                 `json:"es_subscription"`
}
type systemComponentCheck struct {
	Name           string `json:"name"`
	Path           string `json:"path"`
	Exists         *bool  `json:"exists"`
	TrustedPath    *bool  `json:"trusted_path"`
	Signature      *bool  `json:"valid_product_signature"`
	Entitlement    *bool  `json:"es_entitlement,omitempty"`
	CollectionOnly *bool  `json:"supports_collection_only,omitempty"`
	Code           string `json:"code"`
}
