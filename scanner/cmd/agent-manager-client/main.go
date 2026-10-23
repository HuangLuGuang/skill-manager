package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
	"skill-manager/scanner/internal/runtimeinfo"
	"skill-manager/scanner/internal/runtimeobservation"
)

var interactiveMutationLockTimeout = 5 * time.Second

func main() {
	runtimeinfo.Version = managedclient.Version
	if len(os.Args) > 1 && (os.Args[1] == "run" || os.Args[1] == "aidr-teleagent-service") {
		runtimeinfo.Current()
	}
	if err := run(os.Args[1:]); err != nil {
		if len(os.Args) < 2 || os.Args[1] != "run" {
			fmt.Fprintln(os.Stderr, "error:", err)
		}
		var hostExit interface{ ExitCode() int }
		if len(os.Args) > 1 && os.Args[1] == "aidr-hook" && errors.As(err, &hostExit) {
			os.Exit(hostExit.ExitCode())
		}
		os.Exit(1)
	}
}

func run(args []string) (runErr error) {
	if len(args) > 0 && args[0] == "aidr-teleagent-service" {
		return aidrTeleAgentService(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-teleagent-serve" {
		return aidrTeleAgentServe(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-managed-install" {
		return aidrManagedInstall(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-desktop" {
		return aidrDesktop(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-plugin-package" {
		return aidrPluginPackage(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-plugin-install" {
		return aidrPluginInstall(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-plugin-doctor" {
		return aidrPluginDoctor(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-hook" {
		return aidrHook(args[1:], os.Stdin, os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-hook-serve" {
		return aidrHookServe(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-enforce" {
		return aidrEnforce(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-system" {
		return aidrSystem(args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "aidr-sync" {
		return aidrSync(args[1:], os.Stdout)
	}
	if len(args) > 0 && (args[0] == "agent-log-collect" || args[0] == "agent-log-state") {
		return agentLogState(args[0], args[1:], os.Stdout)
	}
	if len(args) > 0 && args[0] == "agent-log-read" {
		return readAgentLog(args[1:], os.Stdout)
	}
	if len(args) == 0 {
		return fmt.Errorf("usage: agent-manager-client <configure|connections|switch-connection|agent-settings|set-agent-roots|reset-agent-roots|add-custom-agent|remove-custom-agent|inventory|cached-inventory|register|switch-model|verify-model|restore-model|takeover|scan-history|refresh-scan-history|pending|refresh-pending|submit-pending|discard-pending|discard-quarantine|available-skills|skill-preview|skill-versions|install-skill|install-skills|quarantine|queue-quarantine|apply-skill-action|backups|restore|run-once|run|local-status|read-notifications|clear-notifications|deliver-notification|service-status|prepare-update|reconcile-service|install-service|uninstall-service|runtime-watch|agent-log-read|agent-log-collect|agent-log-state|aidr-sync|aidr-teleagent-serve> [options]")
	}
	fs := flag.NewFlagSet(args[0], flag.ContinueOnError)
	home := fs.String("home", envOr("AGENT_MANAGER_CLIENT_HOME", userHome()), "Agent home directory")
	server := fs.String("server", envOr("AGENT_MANAGER_CLIENT_SERVER", ""), "Agent Manager URL")
	token := fs.String("token", envOr("AGENT_MANAGER_CLIENT_TOKEN", ""), "client access token")
	name := fs.String("name", "", "client display name")
	skillsPath := fs.String("skills-path", "", "custom Agent Skill directory")
	confirm := fs.Bool("confirm", false, "apply takeover after showing the plan")
	recoverySnapshot := fs.Bool("recovery", false, "include recovery partitions in the local snapshot")
	desktopRequest := fs.String("desktop-request", "", "platform desktop request as JSON")
	forceServiceRestart := fs.Bool("force-restart", false, "restart an installed background service even when its binary is current")
	backup := fs.String("backup", "", "backup name to restore")
	itemID := fs.String("id", "", "pending or quarantine item ID")
	agentType := fs.String("agent-type", "", "local agent type")
	managedAgentID := fs.String("managed-agent-id", "", "managed Agent ID")
	model := fs.String("model", "", "gateway model name")
	gatewaySource := fs.String("gateway-source", "", "model gateway source")
	modelParameters := fs.String("model-parameters", "{}", "Agent-specific model parameters as JSON")
	modelRevision := fs.String("model-revision", "", "expected model configuration revision")
	modelChangeID := fs.String("model-change-id", "", "model configuration recovery ID")
	skillID := fs.String("skill-id", "", "platform Skill ID")
	versionID := fs.String("version-id", "", "trusted platform Skill version ID")
	query := fs.String("query", "", "Skill name search")
	expectedSignature := fs.String("expected-signature", "", "content signature selected for a Skill action")
	expectedTargetSignature := fs.String("expected-target-signature", "", "current target content selected for backup restoration")
	skillAction := fs.String("action", "", "authorized Skill remediation action")
	requestID := fs.String("request-id", "", "idempotency ID for a manual Skill action")
	retainCopy := fs.Bool("retain-copy", true, "retain a recovery copy when uninstalling")
	logDays := fs.Int("days", 0, "diagnostic retention or export range in days")
	outputDir := fs.String("output-dir", "", "diagnostic ZIP output directory")
	interval := fs.Duration("interval", 5*time.Minute, "daemon polling interval")
	runtimeSocket := fs.String("socket", "", "root runtime observation relay Unix socket")
	runtimeReconnect := fs.Duration("reconnect", time.Second, "runtime observation reconnect delay")
	runtimeHealthTimeout := fs.Duration("health-timeout", 5*time.Second, "runtime observer heartbeat timeout")
	var agentMappings stringList
	var installTargets stringList
	var selectedSkills stringList
	var skillRoots stringList
	fs.Var(&agentMappings, "agent", "agent mapping in local-type=managed-agent-id form")
	fs.Var(&installTargets, "install-target", "installation target in local-type=managed-agent-id form")
	fs.Var(&selectedSkills, "skill", "selected local Skill path")
	fs.Var(&skillRoots, "skill-root", "built-in Agent Skill directory; repeat for multiple directories")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if args[0] == "runtime-watch" {
		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer cancel()
		return runtimeobservation.Watch(ctx, os.Stdout, runtimeobservation.WatchOptions{
			SocketPath: *runtimeSocket, ReconnectDelay: *runtimeReconnect, HealthTimeout: *runtimeHealthTimeout,
		})
	}
	started := time.Now()
	defer func() { managedclient.RecordCommandDiagnostic(*home, args[0], started, runErr) }()
	if err := managedclient.EnsureDataLayout(*home); err != nil {
		return fmt.Errorf("初始化客户端数据目录失败: %w", err)
	}
	if args[0] == "record-desktop-diagnostic" {
		data, err := io.ReadAll(io.LimitReader(os.Stdin, 16385))
		if err != nil {
			return err
		}
		if len(data) > 16384 {
			return fmt.Errorf("diagnostics_record_too_large")
		}
		return managedclient.RecordDesktopDiagnostic(*home, data)
	}
	if args[0] == "log-settings" {
		root := filepath.Join(*home, ".agent-manager")
		var value managedclient.LogSettings
		var err error
		if *logDays != 0 {
			value, err = managedclient.SaveLogSettings(root, *logDays)
		} else {
			value, err = managedclient.ReadLogSettings(root)
		}
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(value)
	}
	if args[0] == "export-diagnostics" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		if *outputDir == "" {
			*outputDir = filepath.Join(*home, "Downloads")
		}
		if *logDays == 0 {
			*logDays = 3
			settings, err := managedclient.ReadLogSettings(filepath.Join(*home, ".agent-manager"))
			if err != nil {
				return err
			}
			if *logDays > settings.RetentionDays {
				*logDays = settings.RetentionDays
			}
		}
		path, err := store.ExportDiagnostics(*outputDir, *logDays)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]string{"path": path})
	}
	if args[0] == "desktop-platform" {
		var request managedclient.DesktopRequest
		decoder := json.NewDecoder(strings.NewReader(*desktopRequest))
		decoder.DisallowUnknownFields()
		if len(*desktopRequest) > 16384 || decoder.Decode(&request) != nil || request.Version != 1 {
			return fmt.Errorf("client_ipc_invalid_request")
		}
		result, err := managedclient.DesktopPlatform(context.Background(), *home, request)
		if err != nil {
			return json.NewEncoder(os.Stdout).Encode(map[string]string{"error": err.Error()})
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"result": result})
	}
	config, err := managedclient.LoadConfig(*home)
	if err != nil {
		return err
	}
	if args[0] == "connections" {
		items := make([]map[string]any, 0, len(config.Connections))
		for _, connection := range config.Connections {
			items = append(items, map[string]any{
				"server": connection.Server,
				"name":   connection.Name,
				"active": connection.Server == config.Server,
			})
		}
		return json.NewEncoder(os.Stdout).Encode(items)
	}
	if args[0] == "switch-connection" {
		connection, ok := config.FindConnection(*server)
		if !ok {
			return fmt.Errorf("connection_profile_not_found")
		}
		*server, *token, *name = connection.Server, connection.Token, connection.Name
		inventory, discoverErr := managedclient.Discover(*home)
		if discoverErr != nil {
			return discoverErr
		}
		if connection.Name != "" {
			inventory.Name = connection.Name
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := managedclient.NewAPI(connection.Server, connection.Token, 30*time.Second).Register(ctx, inventory); err != nil {
			return err
		}
	}
	previousServer := strings.TrimRight(strings.TrimSpace(config.Server), "/")
	previousToken := strings.TrimSpace(config.Token)
	if *server == "" {
		*server = config.Server
	}
	if *token == "" {
		*token = config.Token
	}
	if *name == "" && args[0] != "add-custom-agent" {
		*name = config.Name
	}
	if args[0] == "configure" || args[0] == "switch-connection" {
		config.Server = strings.TrimRight(strings.TrimSpace(*server), "/")
		config.Token = strings.TrimSpace(*token)
		config.Name = *name
		if config.Server == "" || config.Token == "" {
			return fmt.Errorf("server and token are required")
		}
		connectionChanged := previousServer != "" && previousToken != "" &&
			(previousServer != config.Server || previousToken != config.Token)
		if connectionChanged {
			releaseRun, err := managedclient.AcquireRunLock(*home)
			if err != nil {
				return fmt.Errorf("connection_runtime_busy")
			}
			defer releaseRun()
			releaseMutation, err := managedclient.AcquireMutationLock(*home)
			if err != nil {
				return err
			}
			defer releaseMutation()
			store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
			if err != nil {
				return fmt.Errorf("无法清理旧平台关联状态: %w", err)
			}
			defer store.Close()
			if err := store.ResetForConnectionChange(); err != nil {
				return fmt.Errorf("无法清理旧平台关联状态: %w", err)
			}
		}
		if err := managedclient.SaveConfig(*home, config); err != nil {
			return err
		}
		fmt.Println("configuration saved")
		return nil
	}
	if args[0] == "add-custom-agent" {
		item, err := managedclient.AddCustomAgent(*home, *name, *skillsPath)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(item)
	}
	if args[0] == "remove-custom-agent" {
		if err := managedclient.RemoveCustomAgent(*home, *agentType); err != nil {
			return err
		}
		fmt.Println("custom Agent removed")
		return nil
	}
	if args[0] == "agent-settings" {
		settings, err := managedclient.BuiltinAgentSettings(*home)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(settings)
	}
	if args[0] == "set-agent-roots" {
		if err := managedclient.SetBuiltinAgentRoots(*home, *agentType, skillRoots); err != nil {
			return err
		}
		fmt.Println("built-in Agent Skill directories updated")
		return nil
	}
	if args[0] == "reset-agent-roots" {
		if err := managedclient.ResetBuiltinAgentRoots(*home, *agentType); err != nil {
			return err
		}
		fmt.Println("built-in Agent Skill directories reset")
		return nil
	}
	if args[0] == "install-service" {
		executable, err := os.Executable()
		if err != nil {
			return err
		}
		path, err := managedclient.InstallService(*home, executable)
		if err != nil {
			return err
		}
		fmt.Println("service installed:", path)
		return nil
	}
	if args[0] == "service-status" {
		status := managedclient.ServiceRuntimeStatus(*home)
		status["proxy"] = hooks.TeleAgentProxyStatus(context.Background(), *home)
		return json.NewEncoder(os.Stdout).Encode(status)
	}
	if args[0] == "prepare-update" {
		state, err := managedclient.StopServiceForUpdate(*home)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(state)
	}
	if args[0] == "stage-update" {
		executable, err := os.Executable()
		if err != nil {
			return err
		}
		state, err := managedclient.ReconcileService(*home, executable, false)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(state)
	}
	if args[0] == "reconcile-service" {
		executable, err := os.Executable()
		if err != nil {
			return err
		}
		result, err := managedclient.ReconcileService(*home, executable, *forceServiceRestart)
		if err != nil {
			return err
		}
		if err = hooks.EnsureTeleAgentProxyService(*home, executable); err != nil {
			fmt.Fprintln(os.Stderr, "client_teleagent_service_degraded:", err)
		}
		return json.NewEncoder(os.Stdout).Encode(result)
	}
	if args[0] == "uninstall-service" {
		if err := managedclient.UninstallService(*home); err != nil {
			return err
		}
		fmt.Println("service uninstalled")
		return nil
	}
	if args[0] == "backups" {
		if *backup != "" {
			items, err := managedclient.PlanBackupRestore(*home, *backup)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		items, err := managedclient.ListBackups(*home)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(items)
	}
	if args[0] == "restore" {
		if !*confirm {
			return fmt.Errorf("restore requires --confirm")
		}
		if *server == "" || *token == "" || *requestID == "" {
			return fmt.Errorf("restore requires credentials and --request-id")
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		result, err := managedclient.RequestBackupRestore(ctx, *home, *backup, *requestID, managedclient.NewAPI(*server, *token, 30*time.Second), store)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(result)
	}
	if args[0] == "request-skill-action" {
		if *server == "" || *token == "" || *agentType == "" || len(selectedSkills) != 1 || *expectedSignature == "" || *requestID == "" {
			return fmt.Errorf("request-skill-action requires credentials, --agent-type, --skill, --expected-signature and --request-id")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		inventory, err := managedclient.Discover(*home)
		if err != nil {
			return err
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		if err := store.EnrichInventory(&inventory); err != nil {
			return err
		}
		if err := api.ReportInventory(ctx, inventory); err != nil {
			return err
		}
		task, err := api.RequestSkillAction(ctx, inventory.ClientID, managedclient.SkillActionRequest{
			RequestID: *requestID, Action: *skillAction, AgentType: *agentType,
			Path: selectedSkills[0], ExpectedSignature: *expectedSignature, VersionID: *versionID,
			QuarantineID:            *itemID,
			ExpectedTargetSignature: *expectedTargetSignature,
			RetainCopy:              *retainCopy,
		})
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(task)
	}
	if args[0] == "apply-skill-action" {
		if *server == "" || *token == "" || *agentType == "" || len(selectedSkills) != 1 || *expectedSignature == "" || *requestID == "" || (*skillAction != "uninstall" && *skillAction != "quarantine") {
			return fmt.Errorf("apply-skill-action requires credentials, --action uninstall|quarantine, --agent-type, --skill, --expected-signature and --request-id")
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		err = managedclient.ExecuteImmediateSkillAction(ctx, *home, managedclient.NewAPI(*server, *token, 10*time.Second), store, managedclient.SkillActionRequest{
			RequestID: *requestID, Action: *skillAction, AgentType: *agentType,
			Path: selectedSkills[0], ExpectedSignature: *expectedSignature,
			VersionID: *versionID, RetainCopy: *retainCopy,
		}, *name)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]string{"request_id": *requestID, "status": "succeeded"})
	}
	if args[0] == "submit-observed" {
		if *server == "" || *token == "" || *agentType == "" || len(selectedSkills) != 1 || *expectedSignature == "" {
			return fmt.Errorf("submit-observed requires credentials, --agent-type, --skill and --expected-signature")
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		api := managedclient.NewAPI(*server, *token, 2*time.Minute)
		result, err := managedclient.SubmitDiscoveredSkillWithResult(ctx, *home, api, store, *agentType, selectedSkills[0], *expectedSignature)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(result)
	}
	if args[0] == "scan-history" || args[0] == "refresh-scan-history" || args[0] == "pending" || args[0] == "refresh-pending" || args[0] == "submit-pending" || args[0] == "discard-pending" || args[0] == "discard-quarantine" || args[0] == "quarantine" || args[0] == "queue-quarantine" {

		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		if args[0] == "scan-history" || args[0] == "refresh-scan-history" {
			var items []managedclient.PendingItem
			if args[0] == "refresh-scan-history" && *server != "" && *token != "" {
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()
				items, err = managedclient.RefreshScanHistory(ctx, *server, *token, store)
			} else {
				items, err = store.ScanHistory()
			}
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		if args[0] == "pending" {
			items, err := store.PendingItems()
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		if args[0] == "refresh-pending" {
			if *server == "" || *token == "" {
				return fmt.Errorf("refresh-pending requires --server and --token")
			}
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
			defer cancel()
			items, err := managedclient.RefreshPendingIncludingTerminal(ctx, *server, *token, store)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		if args[0] == "submit-pending" {
			if *server == "" || *token == "" || strings.TrimSpace(*itemID) == "" {
				return fmt.Errorf("submit-pending requires --server, --token and --id")
			}
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
			defer cancel()
			result, err := managedclient.SubmitPending(ctx, *home, *server, *token, store, *itemID)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(result)
		}
		if args[0] == "discard-pending" {
			if strings.TrimSpace(*itemID) == "" || !*confirm {
				return fmt.Errorf("discard-pending requires --id and --confirm")
			}
			item, err := store.DiscardPending(*itemID)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(item)
		}
		if args[0] == "discard-quarantine" {
			if strings.TrimSpace(*itemID) == "" || strings.TrimSpace(*expectedSignature) == "" || !*confirm {
				return fmt.Errorf("discard-quarantine requires --id, --expected-signature and --confirm")
			}
			item, err := store.DiscardQuarantine(*itemID, *expectedSignature)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(item)
		}
		if args[0] == "quarantine" {
			items, err := store.QuarantineItems()
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		if args[0] == "queue-quarantine" {
			if strings.TrimSpace(*itemID) == "" {
				return fmt.Errorf("queue-quarantine requires --id")
			}
			item, err := managedclient.QueueQuarantineForDetectionExpected(*home, store, *itemID, *expectedSignature)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(item)
		}
	}
	if args[0] == "local-snapshot" {
		snapshot, err := managedclient.DesktopSnapshot(context.Background(), *home, *recoverySnapshot)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(snapshot)
	}
	if args[0] == "local-status" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		status, err := store.LocalStatus()
		if err != nil {
			return err
		}
		details := map[string]any{"source": "desktop"}
		if revision, eventType, revisionErr := store.LatestUIEvent(); revisionErr == nil {
			details["revision"] = revision
			details["event_type"] = eventType
		}
		store.LogDiagnostic("info", "desktop", "desktop_snapshot_refreshed", details)
		return json.NewEncoder(os.Stdout).Encode(status)
	}
	if args[0] == "cached-inventory" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		cached, err := loadCachedInventory(store)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(cached)
	}
	if args[0] == "read-notifications" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		if strings.TrimSpace(*itemID) != "" {
			id, parseErr := strconv.ParseInt(*itemID, 10, 64)
			if parseErr != nil {
				return fmt.Errorf("invalid notification id")
			}
			err = store.MarkNotificationRead(id)
		} else {
			err = store.MarkNotificationsRead()
		}
		if err != nil {
			return err
		}
		fmt.Println("notifications marked as read")
		return nil
	}
	if args[0] == "deliver-notification" {
		id, parseErr := strconv.ParseInt(strings.TrimSpace(*itemID), 10, 64)
		if parseErr != nil {
			return fmt.Errorf("deliver-notification requires --id")
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		return store.MarkNotificationDelivered(id)
	}
	if args[0] == "clear-notifications" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		return store.ClearNotifications()
	}
	if args[0] == "available-skills" || args[0] == "skill-preview" || args[0] == "skill-versions" {
		if *server == "" || *token == "" || strings.TrimSpace(*agentType) == "" {
			return fmt.Errorf("%s requires --server, --token and --agent-type", args[0])
		}
		hostname, _ := os.Hostname()
		clientID := managedclient.DeviceID(hostname, *home)
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		if args[0] == "available-skills" {
			items, err := api.AvailableSkills(ctx, clientID, *agentType, *managedAgentID, strings.TrimSpace(*query), strings.TrimSpace(*skillID))
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		if strings.TrimSpace(*skillID) == "" {
			return fmt.Errorf("%s requires --skill-id", args[0])
		}
		if args[0] == "skill-versions" {
			item, err := api.SkillVersions(ctx, clientID, *skillID, *agentType, *managedAgentID)
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(item)
		}
		item, err := api.SkillPreview(ctx, clientID, *skillID, *versionID, *agentType, *managedAgentID)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(item)
	}
	var inventory managedclient.Inventory
	if args[0] == "takeover" && !*confirm {
		store, storeErr := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if storeErr == nil {
			inventory, err = loadCachedInventory(store)
			store.Close()
		}
	}
	if inventory.ClientID == "" {
		inventory, err = managedclient.Discover(*home)
	}
	if err != nil {
		return err
	}
	if strings.TrimSpace(*name) != "" {
		inventory.Name = strings.TrimSpace(*name)
	}
	switch args[0] {
	case "inventory":
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		if err := store.EnrichInventory(&inventory); err != nil {
			return err
		}
		if err := store.SaveInventory(inventory); err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(inventory)
	case "register":
		if *server == "" || *token == "" {
			return fmt.Errorf("register requires --server and --token")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := managedclient.NewAPI(*server, *token, 30*time.Second).Register(ctx, inventory); err != nil {
			return err
		}
		fmt.Printf("registered %s with %d agents\n", inventory.ClientID, len(inventory.Agents))
		return nil
	case "switch-model":
		if *server == "" || *token == "" || strings.TrimSpace(*agentType) == "" || strings.TrimSpace(*model) == "" {
			return fmt.Errorf("switch-model requires --server, --token, --agent-type and --model")
		}
		localAgentID := strings.TrimSpace(*agentType)
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		api := managedclient.NewAPI(*server, *token, 2*time.Minute)
		parameters := map[string]any{}
		if err := json.Unmarshal([]byte(*modelParameters), &parameters); err != nil {
			return fmt.Errorf("model_config.parameter_invalid")
		}
		if err := managedclient.ValidateModelParameters(*agentType, parameters); err != nil {
			return err
		}
		revision := *modelRevision
		if revision == "" {
			revision, err = managedclient.ModelConfigRevision(*home, *agentType)
			if err != nil {
				return err
			}
		}
		if err := managedclient.ConfigureAgentModel(ctx, *home, inventory, api, store, localAgentID, *agentType, *managedAgentID, *model, map[string]any{"parameters": parameters, "expected_revision": revision, "gateway_source": strings.TrimSpace(*gatewaySource)}); err != nil {
			return err
		}
		fresh, err := managedclient.Discover(*home)
		if err == nil {
			_ = store.EnrichInventory(&fresh)
			_ = store.SaveInventory(fresh)
			_ = api.ReportInventory(ctx, fresh)
		}
		fmt.Println("model_config.pending_restart")
		return nil
	case "verify-model", "restore-model":
		if *agentType == "" && args[0] == "restore-model" {
			return managedclient.RestoreModelConfig(*home, *modelChangeID)
		}
		if *server == "" || *token == "" || *agentType == "" {
			return fmt.Errorf("model operation requires --server, --token and --agent-type")
		}
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		operation := "verify_model_config"
		if args[0] == "restore-model" {
			operation = "restore_model_config"
		}
		err = managedclient.ConfigureModelOperation(ctx, *home, *agentType, operation, api, inventory, store)
		fresh, discoveryErr := managedclient.Discover(*home)
		if discoveryErr == nil {
			_ = store.SaveInventory(fresh)
			_ = api.ReportInventory(ctx, fresh)
		}
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(managedclient.InspectModelConfig(*home, *agentType))
	case "install-skill":
		if *server == "" || *token == "" || strings.TrimSpace(*agentType) == "" || strings.TrimSpace(*skillID) == "" {
			return fmt.Errorf("install-skill requires --server, --token, --agent-type and --skill-id")
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		api := managedclient.NewAPI(*server, *token, 2*time.Minute)
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		policy, err := api.Policy(ctx, inventory.ClientID)
		if err != nil {
			return err
		}
		if err := managedclient.InstallApprovedSkillVersion(ctx, *home, inventory, policy, api, store, *agentType, *managedAgentID, *skillID, *versionID); err != nil {
			return err
		}
		fmt.Println("Skill installed")
		return nil
	case "install-skills":
		if *server == "" || *token == "" || strings.TrimSpace(*skillID) == "" || len(installTargets) == 0 {
			return fmt.Errorf("install-skills requires --server, --token, --skill-id and at least one --install-target")
		}
		targets, err := parseInstallTargets(installTargets)
		if err != nil {
			return err
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		api := managedclient.NewAPI(*server, *token, 5*time.Minute)
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
		defer cancel()
		policy, err := api.Policy(ctx, inventory.ClientID)
		if err != nil {
			return err
		}
		encoder := json.NewEncoder(os.Stdout)
		results, err := managedclient.InstallApprovedSkillVersionBatch(ctx, *home, inventory, policy, api, store, targets, *skillID, *versionID, func(progress managedclient.InstallProgress) {
			_ = encoder.Encode(progress)
		})
		if err != nil {
			return err
		}
		return encoder.Encode(map[string]any{"stage": "result", "results": results, "total": len(targets)})
	case "takeover":
		if *server == "" || *token == "" {
			return fmt.Errorf("takeover requires --server and --token")
		}
		mappings, err := parseMappings(agentMappings)
		if err != nil {
			return err
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		if err := store.EnrichInventory(&inventory); err != nil {
			return err
		}
		compareInventory, excludedPaths := filterInventorySkills(inventory, selectedSkills)
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if *confirm {
			policy, err := api.Policy(ctx, inventory.ClientID)
			if err != nil {
				return err
			}
			if policy.Classification != nil && policy.Classification.Enabled {
				return managedclient.RunFullScan(ctx, *home, api, store)
			}
		}
		if err := api.ReportInventory(ctx, inventory); err != nil {
			cancel()
			return fmt.Errorf("同步最新 Agent 清单失败: %w", err)
		}
		comparisons, err := api.Compare(ctx, compareInventory, mappings)
		cancel()
		if err != nil {
			return err
		}
		plan := managedclient.BuildTakeoverPlan(compareInventory, comparisons)
		plan.ExcludedPaths = append(plan.ExcludedPaths, excludedPaths...)
		if !*confirm {
			return json.NewEncoder(os.Stdout).Encode(plan)
		}
		backup, err := managedclient.ConfirmTakeover(context.Background(), *home, &plan, store)
		if err != nil {
			return err
		}
		fresh, err := managedclient.Discover(*home)
		if err != nil {
			return err
		}
		if err := store.EnrichInventory(&fresh); err != nil {
			return err
		}
		reportCtx, reportCancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer reportCancel()
		if err := api.ReportInventory(reportCtx, fresh); err != nil {
			return err
		}
		managedCount := 0
		pendingCount := 0
		for _, item := range plan.Items {
			if item.Action == "manage" {
				managedCount++
			} else if item.Action == "pending" {
				pendingCount++
			}
		}
		if err := api.ReportTakeover(reportCtx, fresh.ClientID, backup, managedCount, pendingCount); err != nil {
			return err
		}
		fmt.Println("backup:", backup)
		return nil
	case "run-once", "run":
		if *server == "" || *token == "" {
			return fmt.Errorf("%s requires --server and --token", args[0])
		}
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		releaseLock, err := managedclient.AcquireRunLock(*home)
		if err != nil {
			if args[0] == "run-once" && errors.Is(err, managedclient.ErrAlreadyRunning) {
				if err := managedclient.RequestFullScan(*home); err != nil {
					return err
				}
				fmt.Println("后台巡检已收到完整巡检请求")
				return nil
			}
			return err
		}
		defer releaseLock()
		if args[0] == "run" {
			stopCapture, err := managedclient.CaptureDaemonOutput(*home)
			if err != nil {
				fmt.Fprintln(os.Stderr, "client_output_capture_failed:", err)
			} else {
				defer stopCapture()
			}
		}
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		if args[0] == "run" {
			runContext, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			watcher, closeMonitor := managedclient.StartSkillMonitor(runContext, *home, store)
			defer closeMonitor()
			return managedclient.RunDaemon(runContext, *home, api, store, *interval, watcher)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
		defer cancel()
		return managedclient.RunFullScan(ctx, *home, api, store)

	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func loadCachedInventory(store *managedclient.Store) (managedclient.Inventory, error) {
	body, ok, err := store.State("inventory")
	if err != nil {
		return managedclient.Inventory{}, err
	}
	if !ok {
		return managedclient.Inventory{}, fmt.Errorf("cached inventory is unavailable")
	}
	var cached managedclient.Inventory
	if err := json.Unmarshal([]byte(body), &cached); err != nil || cached.ClientID == "" {
		return managedclient.Inventory{}, fmt.Errorf("cached inventory is invalid")
	}
	if cached.DiscoveryVersion != managedclient.InventoryCacheVersion {
		return managedclient.Inventory{}, fmt.Errorf("cached inventory is outdated")
	}
	return cached, nil
}

func filterInventorySkills(inventory managedclient.Inventory, selectedSkills []string) (managedclient.Inventory, []string) {
	if len(selectedSkills) == 0 {
		return inventory, nil
	}
	selected := make(map[string]bool, len(selectedSkills))
	for _, value := range selectedSkills {
		selected[filepath.Clean(value)] = true
	}
	filtered := inventory
	filtered.Agents = nil
	excluded := []string{}
	for _, agent := range inventory.Agents {
		skills := make([]managedclient.Skill, 0, len(agent.Skills))
		for _, skill := range agent.Skills {
			if selected[filepath.Clean(skill.Path)] {
				skills = append(skills, skill)
			} else {
				excluded = append(excluded, skill.Path)
			}
		}
		if len(skills) > 0 {
			agent.Skills = skills
			filtered.Agents = append(filtered.Agents, agent)
		}
	}
	return filtered, excluded
}

type stringList []string

func (values *stringList) String() string {
	return strings.Join(*values, ",")
}

func (values *stringList) Set(value string) error {
	*values = append(*values, value)
	return nil
}

func parseMappings(values []string) (map[string]string, error) {
	result := map[string]string{}
	for _, value := range values {
		parts := strings.SplitN(value, "=", 2)
		if len(parts) != 2 || strings.TrimSpace(parts[0]) == "" || strings.TrimSpace(parts[1]) == "" {
			return nil, fmt.Errorf("invalid --agent mapping %q", value)
		}
		result[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
	}
	return result, nil
}

func parseInstallTargets(values []string) ([]managedclient.InstallTarget, error) {
	result := make([]managedclient.InstallTarget, 0, len(values))
	for _, value := range values {
		parts := strings.SplitN(value, "=", 2)
		agentType := strings.TrimSpace(parts[0])
		if agentType == "" {
			return nil, fmt.Errorf("invalid --install-target %q", value)
		}
		managedAgentID := ""
		if len(parts) == 2 {
			managedAgentID = strings.TrimSpace(parts[1])
		}
		result = append(result, managedclient.InstallTarget{AgentType: agentType, ManagedAgentID: managedAgentID})
	}
	return result, nil
}

func envOr(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func userHome() string {
	if current, err := user.Current(); err == nil {
		return current.HomeDir
	}
	return "."
}
