package gui

import (
	"context"
	"flag"
	"fmt"
	"net/url"
	"path/filepath"
	"strings"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"

	"skill-manager/scanner/internal/client"
	"skill-manager/scanner/internal/config"
	"skill-manager/scanner/internal/discovery"
	"skill-manager/scanner/internal/manifest"
	"skill-manager/scanner/internal/report"
	"skill-manager/scanner/internal/runner"
)

type skillItem struct {
	Path        string
	Name        string
	Description string
	FileCount   int
	TotalBytes  int64
	Error       string
}

type guiState struct {
	skills         []skillItem
	selected       map[string]bool
	latestReport   report.Report
	latestDetail   string
	skillContainer *fyne.Container
	resultRows     [][]string
	resultLinks    []string
	resultTable    *widget.Table
}

func Run(args []string) error {
	fs := flag.NewFlagSet("gui", flag.ContinueOnError)
	if err := fs.Parse(args); err != nil {
		return err
	}

	a := app.NewWithID("com.riversecurity.skill-scanner")
	a.Settings().SetTheme(theme.LightTheme())
	prefs := a.Preferences()
	w := a.NewWindow("Skill Scanner")
	w.Resize(fyne.NewSize(1180, 780))

	state := &guiState{selected: map[string]bool{}}
	rootEntry := widget.NewEntry()
	rootEntry.SetPlaceHolder("/Users/me/.openclaw/workspace/skills")
	outputEntry := widget.NewEntry()
	outputEntry.SetText(prefs.StringWithFallback("output", "skill-scan-report.json"))
	ignoreEntry := widget.NewMultiLineEntry()
	ignoreEntry.SetText(prefs.StringWithFallback("ignore", config.DefaultIgnoreList()))
	ignoreEntry.SetMinRowsVisible(2)

	serverEntry := widget.NewEntry()
	serverEntry.SetText(prefs.StringWithFallback("server", ""))
	serverEntry.SetPlaceHolder("https://skill-manager.example.com")
	tokenEntry := widget.NewPasswordEntry()
	tokenEntry.SetText(prefs.StringWithFallback("token", ""))
	tokenEntry.SetPlaceHolder("smsc_live_xxx")
	hostEntry := widget.NewEntry()
	hostEntry.SetText(prefs.StringWithFallback("host_id", ""))
	hostEntry.SetPlaceHolder("customer-prod-01")
	uploadCheck := widget.NewCheck("上传到服务端", nil)
	uploadCheck.SetChecked(prefs.BoolWithFallback("upload", true))

	behavioralCheck := widget.NewCheck("规则分析", nil)
	behavioralCheck.SetChecked(prefs.BoolWithFallback("behavioral", false))
	sandboxCheck := widget.NewCheck("Sandbox", nil)
	sandboxCheck.SetChecked(prefs.BoolWithFallback("sandbox", false))
	llmCheck := widget.NewCheck("LLM 分析", nil)
	llmCheck.SetChecked(prefs.BoolWithFallback("llm", false))

	timeoutEntry := widget.NewEntry()
	timeoutEntry.SetText(prefs.StringWithFallback("timeout", "120"))
	maxFileEntry := widget.NewEntry()
	maxFileEntry.SetText(prefs.StringWithFallback("max_file", "20"))
	maxTotalEntry := widget.NewEntry()
	maxTotalEntry.SetText(prefs.StringWithFallback("max_total", "50"))
	maxFilesEntry := widget.NewEntry()
	maxFilesEntry.SetText(prefs.StringWithFallback("max_files", "2000"))

	statusLabel := widget.NewLabel("请选择目录并点击发现 Skills")
	statusLabel.Wrapping = fyne.TextWrapWord
	summaryLabel := widget.NewLabel("发现 0 个，已提交 0 个，失败 0 个")
	summaryLabel.TextStyle = fyne.TextStyle{Bold: true}
	openDetailButton := widget.NewButtonWithIcon("打开选中详情", theme.NavigateNextIcon(), func() {
		if state.latestDetail == "" {
			dialog.ShowInformation("暂无详情", "请先在结果表格中选择一条有服务端链接的记录。", w)
			return
		}
		parsed, err := url.Parse(state.latestDetail)
		if err != nil {
			dialog.ShowError(err, w)
			return
		}
		_ = a.OpenURL(parsed)
	})
	openDetailButton.Disable()

	state.skillContainer = container.NewVBox(widget.NewLabel("尚未发现 skill"))
	skillScroll := container.NewVScroll(state.skillContainer)
	skillScroll.SetMinSize(fyne.NewSize(420, 430))
	state.resultRows = [][]string{{"等待扫描", "-", "-", "-", "-", "-"}}
	state.resultLinks = []string{""}
	state.resultTable = widget.NewTable(
		func() (int, int) {
			return len(state.resultRows) + 1, 6
		},
		func() fyne.CanvasObject {
			label := widget.NewLabel("")
			label.Wrapping = fyne.TextTruncate
			button := widget.NewButton("打开详情", nil)
			button.Hide()
			return container.NewStack(label, button)
		},
		func(id widget.TableCellID, obj fyne.CanvasObject) {
			cell := obj.(*fyne.Container)
			label := cell.Objects[0].(*widget.Label)
			button := cell.Objects[1].(*widget.Button)
			button.Hide()
			label.Show()
			if id.Row == 0 {
				headers := []string{"Skill", "状态", "风险", "发现项", "本地预检", "详情 / 错误"}
				label.TextStyle = fyne.TextStyle{Bold: true}
				label.SetText(headers[id.Col])
				return
			}
			label.TextStyle = fyne.TextStyle{}
			if id.Col == 5 && id.Row-1 < len(state.resultLinks) {
				link := state.resultLinks[id.Row-1]
				if strings.HasPrefix(link, "http://") || strings.HasPrefix(link, "https://") {
					button.SetText("打开详情")
					button.OnTapped = func() {
						state.latestDetail = link
						openDetailButton.Enable()
						parsed, err := url.Parse(link)
						if err != nil {
							dialog.ShowError(err, w)
							return
						}
						_ = a.OpenURL(parsed)
					}
					label.Hide()
					button.Show()
					return
				}
			}
			label.SetText(state.resultRows[id.Row-1][id.Col])
		},
	)
	state.resultTable.OnSelected = func(id widget.TableCellID) {
		if id.Row <= 0 || id.Row-1 >= len(state.resultLinks) {
			return
		}
		link := state.resultLinks[id.Row-1]
		if strings.HasPrefix(link, "http://") || strings.HasPrefix(link, "https://") {
			state.latestDetail = link
			openDetailButton.Enable()
			statusLabel.SetText("已选择详情链接：" + link)
			return
		}
		state.latestDetail = ""
		openDetailButton.Disable()
		statusLabel.SetText("该行没有可跳转的服务端详情链接")
	}
	state.resultTable.SetColumnWidth(0, 190)
	state.resultTable.SetColumnWidth(1, 90)
	state.resultTable.SetColumnWidth(2, 90)
	state.resultTable.SetColumnWidth(3, 70)
	state.resultTable.SetColumnWidth(4, 80)
	state.resultTable.SetColumnWidth(5, 520)
	resultScroll := container.NewScroll(state.resultTable)
	resultScroll.SetMinSize(fyne.NewSize(620, 430))

	browseButton := widget.NewButtonWithIcon("选择目录", theme.FolderOpenIcon(), func() {
		dialog.NewFolderOpen(func(uri fyne.ListableURI, err error) {
			if err != nil {
				dialog.ShowError(err, w)
				return
			}
			if uri != nil {
				rootEntry.SetText(uri.Path())
			}
		}, w).Show()
	})
	discoverButton := widget.NewButtonWithIcon("发现 Skills", theme.SearchIcon(), nil)
	scanButton := widget.NewButtonWithIcon("执行扫描", theme.UploadIcon(), nil)
	scanButton.Disable()
	refreshButton := widget.NewButtonWithIcon("刷新状态", theme.ViewRefreshIcon(), nil)
	refreshButton.Disable()
	selectAllButton := widget.NewButton("全选", func() {
		for _, skill := range state.skills {
			state.selected[skill.Path] = skill.Error == ""
		}
		renderSkills(state)
	})
	clearButton := widget.NewButton("清空", func() {
		for _, skill := range state.skills {
			state.selected[skill.Path] = false
		}
		renderSkills(state)
	})

	saveSettings := func() {
		prefs.SetString("server", serverEntry.Text)
		prefs.SetString("token", tokenEntry.Text)
		prefs.SetString("host_id", hostEntry.Text)
		prefs.SetString("output", outputEntry.Text)
		prefs.SetString("ignore", ignoreEntry.Text)
		prefs.SetBool("upload", uploadCheck.Checked)
		prefs.SetBool("behavioral", behavioralCheck.Checked)
		prefs.SetBool("sandbox", sandboxCheck.Checked)
		prefs.SetBool("llm", llmCheck.Checked)
		prefs.SetString("timeout", timeoutEntry.Text)
		prefs.SetString("max_file", maxFileEntry.Text)
		prefs.SetString("max_total", maxTotalEntry.Text)
		prefs.SetString("max_files", maxFilesEntry.Text)
	}

	discoverButton.OnTapped = func() {
		saveSettings()
		cfg, err := discoverConfig(rootEntry.Text, ignoreEntry.Text, maxFileEntry.Text, maxTotalEntry.Text, maxFilesEntry.Text)
		if err != nil {
			dialog.ShowError(err, w)
			return
		}
		discoverButton.Disable()
		scanButton.Disable()
		statusLabel.SetText("正在发现 Skills...")
		go func() {
			items, err := discoverSkills(cfg)
			if err != nil {
				statusLabel.SetText("发现失败：" + err.Error())
				discoverButton.Enable()
				return
			}
			state.skills = items
			state.selected = map[string]bool{}
			for _, item := range items {
				state.selected[item.Path] = item.Error == ""
			}
			renderSkills(state)
			statusLabel.SetText(fmt.Sprintf("发现 %d 个 skill，默认选择无错误项", len(items)))
			if len(items) > 0 {
				scanButton.Enable()
			}
			discoverButton.Enable()
		}()
	}

	scanButton.OnTapped = func() {
		saveSettings()
		cfg, err := scanConfig(
			rootEntry.Text,
			serverEntry.Text,
			tokenEntry.Text,
			outputEntry.Text,
			hostEntry.Text,
			ignoreEntry.Text,
			timeoutEntry.Text,
			maxFileEntry.Text,
			maxTotalEntry.Text,
			maxFilesEntry.Text,
			uploadCheck.Checked,
			behavioralCheck.Checked,
			sandboxCheck.Checked,
			llmCheck.Checked,
		)
		if err != nil {
			dialog.ShowError(err, w)
			return
		}
		selected := selectedSkills(state)
		if len(selected) == 0 {
			dialog.ShowInformation("未选择 Skill", "请至少选择一个要扫描的 skill。", w)
			return
		}

		state.latestDetail = ""
		openDetailButton.Disable()
		scanButton.Disable()
		refreshButton.Disable()
		discoverButton.Disable()
		statusLabel.SetText("正在扫描，结果会实时刷新...")
		state.resultRows = [][]string{{"扫描开始", "-", "-", "-", "-", "等待第一个结果..."}}
		state.resultLinks = []string{""}
		state.resultTable.Refresh()
		go func() {
			result, outputPath, err := runner.Scan(cfg, runner.Options{
				SelectedPaths: selected,
				OnProgress: func(snapshot report.Report, item report.SkillResult) {
					state.latestReport = snapshot
					if item.Submission.DetailURL != "" {
						state.latestDetail = item.Submission.DetailURL
						openDetailButton.Enable()
					}
					updateReport(state, snapshot, summaryLabel)
					statusLabel.SetText(fmt.Sprintf("正在扫描：%s", defaultString(item.Name, filepath.Base(item.Path))))
				},
			})
			if err != nil {
				statusLabel.SetText("扫描失败：" + err.Error())
				scanButton.Enable()
				discoverButton.Enable()
				refreshButton.Enable()
				return
			}
			state.latestReport = result
			updateReport(state, result, summaryLabel)
			statusLabel.SetText("扫描完成，报告文件：" + outputPath)
			scanButton.Enable()
			discoverButton.Enable()
			refreshButton.Enable()
			go autoRefreshStatuses(state, cfg, statusLabel, summaryLabel, openDetailButton)
		}()
	}

	refreshButton.OnTapped = func() {
		cfg, err := scanConfig(
			rootEntry.Text,
			serverEntry.Text,
			tokenEntry.Text,
			outputEntry.Text,
			hostEntry.Text,
			ignoreEntry.Text,
			timeoutEntry.Text,
			maxFileEntry.Text,
			maxTotalEntry.Text,
			maxFilesEntry.Text,
			uploadCheck.Checked,
			behavioralCheck.Checked,
			sandboxCheck.Checked,
			llmCheck.Checked,
		)
		if err != nil {
			dialog.ShowError(err, w)
			return
		}
		refreshButton.Disable()
		statusLabel.SetText("正在刷新服务端状态...")
		go func() {
			updated, err := refreshSubmittedStatuses(state, cfg)
			if err != nil {
				statusLabel.SetText("刷新失败：" + err.Error())
			} else {
				updateReport(state, state.latestReport, summaryLabel)
				statusLabel.SetText(fmt.Sprintf("已刷新 %d 条服务端状态", updated))
				if state.latestDetail != "" {
					openDetailButton.Enable()
				}
			}
			refreshButton.Enable()
		}()
	}

	scanTop := widget.NewCard("扫描目录", "使用系统目录选择器选择客户本地 skills 根目录", container.NewBorder(nil, nil, nil, browseButton, rootEntry))
	options := widget.NewCard("扫描参数", "这些选项与 CLI 参数保持一致；服务端地址和 Token 在设置页配置", container.NewVBox(
		container.NewGridWithColumns(4, behavioralCheck, sandboxCheck, llmCheck, uploadCheck),
		container.NewGridWithColumns(4,
			widget.NewForm(widget.NewFormItem("超时秒数", timeoutEntry)),
			widget.NewForm(widget.NewFormItem("最大文件数", maxFilesEntry)),
			widget.NewForm(widget.NewFormItem("单文件 MB", maxFileEntry)),
			widget.NewForm(widget.NewFormItem("总大小 MB", maxTotalEntry)),
		),
		widget.NewLabel("忽略目录"),
		ignoreEntry,
	))
	contentSplit := container.NewHSplit(
		widget.NewCard("选择要扫描的 Skills", "每个 skill 独立显示", skillScroll),
		widget.NewCard("扫描结果", "实时刷新；详细结果可点击上方按钮跳转到服务端页面", resultScroll),
	)
	contentSplit.Offset = 0.42
	scanPage := container.NewBorder(
		container.NewVBox(
			scanTop,
			container.NewHBox(discoverButton, selectAllButton, clearButton, scanButton, refreshButton, openDetailButton),
			statusLabel,
			summaryLabel,
		),
		options,
		nil,
		nil,
		contentSplit,
	)

	settingsPage := container.NewVBox(
		widget.NewCard("服务端设置", "这些配置会保存在本机 GUI 偏好设置中，不再占用扫描页面空间", widget.NewForm(
			widget.NewFormItem("Skill Manager Server", serverEntry),
			widget.NewFormItem("Scanner Token", tokenEntry),
			widget.NewFormItem("Host ID", hostEntry),
			widget.NewFormItem("输出报告", outputEntry),
		)),
		widget.NewButtonWithIcon("保存设置", theme.DocumentSaveIcon(), func() {
			saveSettings()
			dialog.ShowInformation("已保存", "服务端设置和扫描参数已保存到本机。", w)
		}),
	)

	tabs := container.NewAppTabs(
		container.NewTabItemWithIcon("扫描", theme.SearchIcon(), scanPage),
		container.NewTabItemWithIcon("设置", theme.SettingsIcon(), settingsPage),
	)
	tabs.SetTabLocation(container.TabLocationTop)
	w.SetContent(tabs)
	w.ShowAndRun()
	return nil
}

func renderSkills(state *guiState) {
	state.skillContainer.Objects = nil
	if len(state.skills) == 0 {
		state.skillContainer.Add(widget.NewLabel("没有发现 skill"))
		state.skillContainer.Refresh()
		return
	}
	for _, item := range state.skills {
		current := item
		check := widget.NewCheck(defaultString(current.Name, filepath.Base(current.Path)), func(value bool) {
			state.selected[current.Path] = value
		})
		check.SetChecked(state.selected[current.Path])
		detailText := strings.TrimSpace(current.Description)
		if detailText == "" {
			detailText = current.Path
		} else {
			detailText += "\n" + current.Path
		}
		if current.Error != "" {
			detailText = "错误：" + current.Error + "\n" + current.Path
		}
		detail := widget.NewLabel(detailText)
		detail.Wrapping = fyne.TextWrapWord
		meta := widget.NewLabel(fmt.Sprintf("%d 文件 · %s", current.FileCount, formatSize(current.TotalBytes)))
		meta.Importance = widget.LowImportance
		card := widget.NewCard("", "", container.NewVBox(check, detail, meta))
		state.skillContainer.Add(card)
	}
	state.skillContainer.Refresh()
}

func updateReport(state *guiState, snapshot report.Report, summaryLabel *widget.Label) {
	rows := make([][]string, 0, len(snapshot.Skills))
	links := make([]string, 0, len(snapshot.Skills))
	for _, item := range snapshot.Skills {
		status := "本地完成"
		if item.Submitted {
			status = defaultString(item.Submission.Status, "已提交")
		}
		detail := item.Submission.DetailURL
		link := detail
		if item.SubmitError != "" {
			status = "失败"
			detail = item.SubmitError
			link = ""
		}
		if detail == "" {
			detail = item.PackagePath
		}
		if strings.HasPrefix(link, "http://") || strings.HasPrefix(link, "https://") {
			detail = "点击行后打开详情"
		}
		rows = append(rows, []string{
			defaultString(item.Name, filepath.Base(item.Path)),
			status,
			defaultString(item.Submission.RiskLevel, "-"),
			fmt.Sprintf("%d", item.Submission.FindingsCount),
			fmt.Sprintf("%d", len(item.LocalFindings)),
			detail,
		})
		links = append(links, link)
	}
	if len(rows) == 0 {
		rows = [][]string{{"暂无结果", "-", "-", "-", "-", "-"}}
		links = []string{""}
	}
	state.resultRows = rows
	state.resultLinks = links
	state.resultTable.Refresh()
	summaryLabel.SetText(fmt.Sprintf("发现 %d 个，已提交 %d 个，失败 %d 个", snapshot.Found, snapshot.Submitted, snapshot.Failed))
}

func autoRefreshStatuses(state *guiState, cfg config.Config, statusLabel *widget.Label, summaryLabel *widget.Label, openDetailButton *widget.Button) {
	if cfg.Server == "" || cfg.Token == "" {
		return
	}
	for attempt := 0; attempt < 40; attempt++ {
		if !hasPendingSubmission(state.latestReport) {
			return
		}
		time.Sleep(3 * time.Second)
		updated, err := refreshSubmittedStatuses(state, cfg)
		if err != nil {
			statusLabel.SetText("自动刷新失败：" + err.Error())
			return
		}
		if updated > 0 {
			updateReport(state, state.latestReport, summaryLabel)
			statusLabel.SetText(fmt.Sprintf("自动刷新 %d 条状态", updated))
			if state.latestDetail != "" {
				openDetailButton.Enable()
			}
		}
	}
}

func refreshSubmittedStatuses(state *guiState, cfg config.Config) (int, error) {
	if cfg.Server == "" {
		return 0, fmt.Errorf("请先在设置页配置 Skill Manager Server")
	}
	if cfg.Token == "" {
		return 0, fmt.Errorf("请先在设置页配置 Scanner Token")
	}
	if len(state.latestReport.Skills) == 0 {
		return 0, fmt.Errorf("当前没有可刷新的扫描结果")
	}
	apiClient := client.New(cfg.Server, cfg.Token, cfg.Timeout)
	updated := 0
	for idx := range state.latestReport.Skills {
		item := &state.latestReport.Skills[idx]
		if !item.Submitted || item.Submission.SkillID == "" {
			continue
		}
		if !shouldRefreshStatus(item.Submission.Status) {
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), cfg.Timeout)
		result, err := apiClient.GetImport(ctx, item.Submission.SkillID)
		cancel()
		if err != nil {
			item.SubmitError = err.Error()
			updated++
			continue
		}
		if result.Name == "" {
			result.Name = item.Name
		}
		if result.DetailURL == "" {
			result.DetailURL = item.Submission.DetailURL
		}
		item.Submission = result
		item.SubmitError = ""
		if result.DetailURL != "" {
			state.latestDetail = result.DetailURL
		}
		updated++
	}
	return updated, nil
}

func hasPendingSubmission(snapshot report.Report) bool {
	for _, item := range snapshot.Skills {
		if item.Submitted && item.Submission.SkillID != "" && shouldRefreshStatus(item.Submission.Status) {
			return true
		}
	}
	return false
}

func shouldRefreshStatus(status string) bool {
	status = strings.ToUpper(strings.TrimSpace(status))
	return status == "" || status == "PENDING"
}

func selectedSkills(state *guiState) map[string]bool {
	selected := map[string]bool{}
	for _, skill := range state.skills {
		if state.selected[skill.Path] {
			selected[skill.Path] = true
		}
	}
	return selected
}

func discoverSkills(cfg config.Config) ([]skillItem, error) {
	skills, err := discovery.Find(cfg.Root, cfg.IgnoreDirs)
	if err != nil {
		return nil, err
	}
	items := make([]skillItem, 0, len(skills))
	for _, skill := range skills {
		item := skillItem{Path: skill.Path}
		m, err := manifest.Build(skill.Path, manifest.Options{
			IgnoreDirs:    cfg.IgnoreDirs,
			MaxFileBytes:  cfg.MaxFileBytes,
			MaxTotalBytes: cfg.MaxTotalBytes,
			MaxFiles:      cfg.MaxFiles,
		})
		if err != nil {
			item.Error = err.Error()
		} else {
			item.Name = m.Name
			item.Description = m.Description
			item.FileCount = len(m.Files)
			item.TotalBytes = m.TotalBytes
		}
		items = append(items, item)
	}
	return items, nil
}

func discoverConfig(root string, ignore string, maxFileMB string, maxTotalMB string, maxFiles string) (config.Config, error) {
	absRoot, err := filepath.Abs(strings.TrimSpace(root))
	if err != nil {
		return config.Config{}, err
	}
	return config.Config{
		Root:          absRoot,
		Output:        "skill-scan-report.json",
		Timeout:       120 * time.Second,
		MaxFileBytes:  parseMB(maxFileMB, 20),
		MaxTotalBytes: parseMB(maxTotalMB, 50),
		MaxFiles:      parseInt(maxFiles, 2000),
		IgnoreDirs:    config.ParseIgnoreDirs(defaultString(ignore, config.DefaultIgnoreList())),
	}, nil
}

func scanConfig(
	root string,
	server string,
	token string,
	output string,
	hostID string,
	ignore string,
	timeoutValue string,
	maxFileMB string,
	maxTotalMB string,
	maxFiles string,
	upload bool,
	behavioral bool,
	sandbox bool,
	llm bool,
) (config.Config, error) {
	absRoot, err := filepath.Abs(strings.TrimSpace(root))
	if err != nil {
		return config.Config{}, err
	}
	output = strings.TrimSpace(output)
	if output == "" {
		output = filepath.Join(absRoot, "skill-scan-report.json")
	}
	server = strings.TrimSpace(server)
	return config.Config{
		Root:          absRoot,
		Server:        server,
		Token:         strings.TrimSpace(token),
		Output:        output,
		HostID:        strings.TrimSpace(hostID),
		Upload:        upload || server != "",
		UseBehavioral: behavioral,
		UseSandbox:    sandbox,
		UseLLM:        llm,
		Timeout:       time.Duration(parseInt(timeoutValue, 120)) * time.Second,
		MaxFileBytes:  parseMB(maxFileMB, 20),
		MaxTotalBytes: parseMB(maxTotalMB, 50),
		MaxFiles:      parseInt(maxFiles, 2000),
		IgnoreDirs:    config.ParseIgnoreDirs(defaultString(ignore, config.DefaultIgnoreList())),
	}, nil
}

func parseMB(value string, fallback int64) int64 {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback * 1024 * 1024
	}
	var parsed int64
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil || parsed <= 0 {
		parsed = fallback
	}
	return parsed * 1024 * 1024
}

func parseInt(value string, fallback int) int {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback
	}
	var parsed int
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}

func formatSize(size int64) string {
	if size < 1024 {
		return fmt.Sprintf("%d B", size)
	}
	if size < 1024*1024 {
		return fmt.Sprintf("%.1f KB", float64(size)/1024)
	}
	return fmt.Sprintf("%.1f MB", float64(size)/1024/1024)
}

func defaultString(value string, fallback string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback
	}
	return value
}
