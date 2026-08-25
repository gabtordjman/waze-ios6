#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <SystemConfiguration/SystemConfiguration.h>
#import <CFNetwork/CFNetwork.h>
#import <substrate.h>

/*
 * WazeIOS6Fix
 * - Force HTTP proxy (mitmweb) for Waze CFNetwork traffic
 * - Bypass SSL trust evaluation (modern CAs / pinning)
 */

static NSString *const kPrefsPath = @"/var/mobile/Library/Preferences/com.wazeios6.fix.plist";

static BOOL gEnabled = YES;
static BOOL gForceProxy = YES;
static BOOL gKillSSL = YES;
static NSString *gProxyHost = @"192.168.1.191";
static NSInteger gProxyPort = 8080;

static void LoadPrefs(void) {
    NSDictionary *prefs = [NSDictionary dictionaryWithContentsOfFile:kPrefsPath];
    if (!prefs) return;
    if (prefs[@"Enabled"]) gEnabled = [prefs[@"Enabled"] boolValue];
    if (prefs[@"ForceProxy"]) gForceProxy = [prefs[@"ForceProxy"] boolValue];
    if (prefs[@"KillSSL"]) gKillSSL = [prefs[@"KillSSL"] boolValue];
    if ([prefs[@"ProxyHost"] isKindOfClass:[NSString class]] && [prefs[@"ProxyHost"] length])
        gProxyHost = prefs[@"ProxyHost"];
    if (prefs[@"ProxyPort"]) gProxyPort = [prefs[@"ProxyPort"] integerValue];
}

static CFDictionaryRef MakeProxyDict(void) {
    NSDictionary *proxy = @{
        (__bridge NSString *)kCFNetworkProxiesHTTPEnable: @YES,
        (__bridge NSString *)kCFNetworkProxiesHTTPProxy: gProxyHost,
        (__bridge NSString *)kCFNetworkProxiesHTTPPort: @(gProxyPort),
        (__bridge NSString *)kCFNetworkProxiesHTTPSEnable: @YES,
        @"HTTPSProxy": gProxyHost,
        @"HTTPSPort": @(gProxyPort),
    };
    return CFBridgingRetain(proxy);
}

// --------- Force proxy ---------

static CFDictionaryRef (*orig_CFNetworkCopySystemProxySettings)(void);
static CFDictionaryRef repl_CFNetworkCopySystemProxySettings(void) {
    if (gEnabled && gForceProxy) {
        return MakeProxyDict();
    }
    return orig_CFNetworkCopySystemProxySettings();
}

static CFDictionaryRef (*orig_SCDynamicStoreCopyProxies)(SCDynamicStoreRef store);
static CFDictionaryRef repl_SCDynamicStoreCopyProxies(SCDynamicStoreRef store) {
    if (gEnabled && gForceProxy) {
        return MakeProxyDict();
    }
    return orig_SCDynamicStoreCopyProxies(store);
}

// --------- SSL kill (SecTrustEvaluate) ---------

static OSStatus (*orig_SecTrustEvaluate)(SecTrustRef trust, SecTrustResultType *result);
static OSStatus repl_SecTrustEvaluate(SecTrustRef trust, SecTrustResultType *result) {
    if (gEnabled && gKillSSL) {
        if (result) *result = kSecTrustResultProceed;
        return errSecSuccess;
    }
    return orig_SecTrustEvaluate(trust, result);
}

%ctor {
    LoadPrefs();
    MSHookFunction((void *)CFNetworkCopySystemProxySettings,
                   (void *)repl_CFNetworkCopySystemProxySettings,
                   (void **)&orig_CFNetworkCopySystemProxySettings);
    MSHookFunction((void *)SCDynamicStoreCopyProxies,
                   (void *)repl_SCDynamicStoreCopyProxies,
                   (void **)&orig_SCDynamicStoreCopyProxies);
    MSHookFunction((void *)SecTrustEvaluate,
                   (void *)repl_SecTrustEvaluate,
                   (void **)&orig_SecTrustEvaluate);
}
