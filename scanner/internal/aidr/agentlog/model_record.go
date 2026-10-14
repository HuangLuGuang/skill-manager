package agentlog

type modelRecord struct {
	Type    string `json:"type"`
	Message struct {
		Model string `json:"model"`
	} `json:"message"`
	ProviderData struct {
		Model string `json:"model"`
	} `json:"providerData"`
	Payload struct {
		Type     string `json:"type"`
		TurnID   string `json:"turn_id"`
		Model    string `json:"model"`
		Provider string `json:"model_provider"`
		Effort   string `json:"effort"`
		Summary  string `json:"summary"`
	} `json:"payload"`
}
