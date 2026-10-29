package agentlog

func qwenWorkLogAdapter() logAdapter {
	a := lineAdapter(normalizeRequestSetTranscript)
	a.ModelSource = "qwenwork.message.model"
	a.Model = messageModel(a.ModelSource)
	a.DraftTurn = true
	a.SkillField = transcriptSkillField
	return a
}
