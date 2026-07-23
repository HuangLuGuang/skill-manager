package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"skill-manager/scanner/internal/managedclient"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: agent-manager-client <configure|agent-settings|set-agent-roots|reset-agent-roots|add-custom-agent|remove-custom-agent|inventory|cached-inventory|register|takeover|pending|refresh-pending|submit-pending|available-skills|skill-preview|install-skill|quarantine|backups|restore|run-once|run|local-status|read-notifications|clear-notifications|deliver-notification|pause-governance|resume-governance|service-status|install-service|uninstall-service> [options]")
	}
	fs := flag.NewFlagSet(args[0], flag.ContinueOnError)
	home := fs.String("home", envOr("AGENT_MANAGER_CLIENT_HOME", userHome()), "Agent home directory")
	server := fs.String("server", envOr("AGENT_MANAGER_CLIENT_SERVER", ""), "Agent Manager URL")
	token := fs.String("token", envOr("AGENT_MANAGER_CLIENT_TOKEN", ""), "client access token")
	name := fs.String("name", "", "client display name")
	skillsPath := fs.String("skills-path", "", "custom Agent Skill directory")
	confirm := fs.Bool("confirm", false, "apply takeover after showing the plan")
	backup := fs.String("backup", "", "backup name to restore")
	itemID := fs.String("id", "", "pending or quarantine item ID")
	agentType := fs.String("agent-type", "", "local agent type")
	managedAgentID := fs.String("managed-agent-id", "", "managed Agent ID")
	skillID := fs.String("skill-id", "", "platform Skill ID")
	query := fs.String("query", "", "Skill name search")
	interval := fs.Duration("interval", 5*time.Minute, "daemon polling interval")
	var agentMappings stringList
	var selectedSkills stringList
	var skillRoots stringList
	fs.Var(&agentMappings, "agent", "agent mapping in local-type=managed-agent-id form")
	fs.Var(&selectedSkills, "skill", "only take over the selected local skill path")
	fs.Var(&skillRoots, "skill-root", "built-in Agent Skill directory; repeat for multiple directories")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	config, err := managedclient.LoadConfig(*home)
	if err != nil {
		return err
	}
	if *server == "" {
		*server = config.Server
	}
	if *token == "" {
		*token = config.Token
	}
	if *name == "" && args[0] != "add-custom-agent" {
		*name = config.Name
	}
	if args[0] == "configure" {
		config.Server = *server
		config.Token = *token
		config.Name = *name
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
		return json.NewEncoder(os.Stdout).Encode(managedclient.ServiceStatus(*home))
	}
	if args[0] == "uninstall-service" {
		if err := managedclient.UninstallService(*home); err != nil {
			return err
		}
		fmt.Println("service uninstalled")
		return nil
	}
	if args[0] == "backups" {
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
		if err := managedclient.RestoreBackup(*home, *backup); err != nil {
			return err
		}
		fmt.Println("backup restored:", *backup)
		return nil
	}
	if args[0] == "pending" || args[0] == "refresh-pending" || args[0] == "submit-pending" || args[0] == "quarantine" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
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
			items, err := managedclient.RefreshPending(ctx, *server, *token, store)
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
		if args[0] == "quarantine" {
			items, err := store.QuarantineItems()
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
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
	if args[0] == "pause-governance" || args[0] == "resume-governance" {
		store, err := managedclient.OpenStore(filepath.Join(*home, ".agent-manager", "client.db"))
		if err != nil {
			return err
		}
		defer store.Close()
		enabled := args[0] == "resume-governance"
		if err := store.SetGovernanceEnabled(enabled); err != nil {
			return err
		}
		if enabled {
			fmt.Println("持续治理已恢复")
		} else {
			fmt.Println("持续治理已暂停")
		}
		return nil
	}
	if args[0] == "available-skills" || args[0] == "skill-preview" {
		if *server == "" || *token == "" || strings.TrimSpace(*agentType) == "" {
			return fmt.Errorf("%s requires --server, --token and --agent-type", args[0])
		}
		hostname, _ := os.Hostname()
		clientID := managedclient.DeviceID(hostname, *home)
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		if args[0] == "available-skills" {
			items, err := api.AvailableSkills(ctx, clientID, *agentType, *managedAgentID, strings.TrimSpace(*query))
			if err != nil {
				return err
			}
			return json.NewEncoder(os.Stdout).Encode(items)
		}
		if strings.TrimSpace(*skillID) == "" {
			return fmt.Errorf("skill-preview requires --skill-id")
		}
		item, err := api.SkillPreview(ctx, clientID, *skillID, *agentType, *managedAgentID)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(item)
	}
	inventory, err := managedclient.Discover(*home)
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
		if err := managedclient.InstallApprovedSkill(ctx, *home, inventory, policy, api, store, *agentType, *managedAgentID, *skillID); err != nil {
			return err
		}
		if strings.TrimSpace(*itemID) != "" {
			if err := store.RemovePending(*itemID); err != nil {
				return err
			}
		}
		fmt.Println("Skill installed")
		return nil
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
		backup, err := managedclient.ApplyTakeover(*home, &plan)
		if err != nil {
			return err
		}
		if err := managedclient.RecordTakeover(*home, plan, store); err != nil {
			managedclient.RestoreTakeover(plan, backup)
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
		api := managedclient.NewAPI(*server, *token, 30*time.Second)
		var watcher *managedclient.SkillWatcher
		if args[0] == "run" {
			watcher, err = managedclient.NewSkillWatcher()
			if err != nil {
				return fmt.Errorf("无法启动 Skill 文件监控: %w", err)
			}
			defer watcher.Close()
			if err := watcher.Refresh(*home, store); err != nil {
				return fmt.Errorf("无法监听 Skill 目录: %w", err)
			}
		}
		forceFullScan := args[0] == "run-once"
		for {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			var err error
			if forceFullScan {
				err = managedclient.RunFullScan(ctx, *home, api, store)
			} else {
				err = managedclient.RunOnce(ctx, *home, api, store)
			}
			cancel()
			if err != nil {
				if args[0] == "run-once" {
					return err
				}
				fmt.Fprintln(os.Stderr, "sync error:", err)
			}
			if watcher != nil {
				if refreshErr := watcher.Refresh(*home, store); refreshErr != nil {
					fmt.Fprintln(os.Stderr, "watch refresh error:", refreshErr)
				}
			}
			managedclient.DeliverPendingNotifications(store)
			if args[0] == "run-once" {
				return nil
			}
			forceFullScan = managedclient.WaitForRunOrChange(*home, *interval, func() {
				ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
				defer cancel()
				if err := managedclient.PollTasks(ctx, *home, api, store); err != nil {
					fmt.Fprintln(os.Stderr, "task poll error:", err)
				}
			}, watcher.Changes())
		}
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
