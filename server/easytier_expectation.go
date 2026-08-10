package main

import (
	"sort"

	"github.com/cppla/serverstatus/server/contracts"
)

// projectEasyTierExpectation compares explicit operator configuration with the
// sanitised observation only. It deliberately has no effect on device identity
// or authentication.
func projectEasyTierExpectation(expectation *contracts.EasyTierExpectation, stats *EasyTierStats) any {
	if expectation == nil {
		return map[string]any{"configured": false, "result": "not_configured"}
	}
	nodeObserved := stats != nil && !stats.Stale && stats.CommandStatus.NodeInfo.Status == EasyTierHealthy
	routesObserved := stats != nil && !stats.Stale && stats.CommandStatus.RouteList.Status == EasyTierHealthy
	observedCIDRs := map[string]bool{}
	if nodeObserved {
		for _, cidr := range stats.Node.ProxyCIDRs {
			observedCIDRs[cidr] = true
		}
	}
	if routesObserved {
		for _, route := range stats.Routes.Items {
			if !route.IsLocal {
				continue
			}
			for _, cidr := range route.ProxyCIDRs {
				observedCIDRs[cidr] = true
			}
		}
	}
	observed := make([]string, 0, len(observedCIDRs))
	for cidr := range observedCIDRs {
		observed = append(observed, cidr)
	}
	sort.Strings(observed)
	result := "not_observable"
	if nodeObserved && routesObserved && stats.Node.NetworkName != nil && stats.Node.OverlayIPv4 != nil && stats.Node.AdministrativeRole != nil {
		result = "matched"
		if *stats.Node.NetworkName != expectation.NetworkName || *stats.Node.OverlayIPv4 != expectation.OverlayIPv4 || *stats.Node.AdministrativeRole != expectation.AdministrativeRole || !sameStringSet(observed, expectation.ProxyCIDRs) {
			result = "mismatch"
		}
	}
	var administrativeRole, networkName, overlayIPv4 any
	if nodeObserved {
		administrativeRole = stats.Node.AdministrativeRole
		networkName = stats.Node.NetworkName
		overlayIPv4 = stats.Node.OverlayIPv4
	}
	return map[string]any{
		"configured": true,
		"expected":   expectation,
		"observed": map[string]any{
			"administrative_role": administrativeRole,
			"network_name":        networkName,
			"overlay_ipv4":        overlayIPv4,
			"proxy_cidrs":         observed,
		},
		"result": result,
	}
}

func sameStringSet(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	values := map[string]bool{}
	for _, value := range left {
		values[value] = true
	}
	for _, value := range right {
		if !values[value] {
			return false
		}
	}
	return true
}
