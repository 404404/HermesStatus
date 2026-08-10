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
	observedCIDRs := map[string]bool{}
	if stats != nil {
		for _, cidr := range stats.Node.ProxyCIDRs {
			observedCIDRs[cidr] = true
		}
		for _, route := range stats.Routes.Items {
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
	if stats != nil && stats.Node.NetworkName != nil && stats.Node.OverlayIPv4 != nil && stats.Node.AdministrativeRole != nil {
		result = "matched"
		if *stats.Node.NetworkName != expectation.NetworkName || *stats.Node.OverlayIPv4 != expectation.OverlayIPv4 || *stats.Node.AdministrativeRole != expectation.AdministrativeRole || !sameStringSet(observed, expectation.ProxyCIDRs) {
			result = "mismatch"
		}
	}
	return map[string]any{
		"configured": true,
		"expected":   expectation,
		"observed": map[string]any{
			"administrative_role": valueOrNil(stats, func(value *EasyTierStats) *string { return value.Node.AdministrativeRole }),
			"network_name":        valueOrNil(stats, func(value *EasyTierStats) *string { return value.Node.NetworkName }),
			"overlay_ipv4":        valueOrNil(stats, func(value *EasyTierStats) *string { return value.Node.OverlayIPv4 }),
			"proxy_cidrs":         observed,
		},
		"result": result,
	}
}

func valueOrNil(stats *EasyTierStats, getter func(*EasyTierStats) *string) any {
	if stats == nil {
		return nil
	}
	return getter(stats)
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
