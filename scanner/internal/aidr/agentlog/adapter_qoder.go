package agentlog

func qoderLogAdapter() logAdapter {
	a := lineAdapter(normalizeQoder)
	a.ModelSource = "qoder-cli.message.model"
	a.Model = messageModel(a.ModelSource)
	a.DraftTurn = true
	a.SkillField = transcriptSkillField
	a.Repair = func(c Cursor) bool { return c.Offset > 0 && c.ContextRepairVersion < contextRepairVersion }
	return a
}
