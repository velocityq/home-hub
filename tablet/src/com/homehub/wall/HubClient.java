package com.homehub.wall;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Log;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;

/** Keeps the WebView on the hub, and shows a retry page when the hub does not answer. */
class HubClient extends WebViewClient {
    final MainActivity a;

    HubClient(MainActivity a) { this.a = a; }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
        // Stay on the hub. Nothing else may open inside this app.
        Uri hub = Uri.parse(a.hubUrl());
        Uri to = req.getUrl();
        return !(hub.getHost() != null && hub.getHost().equals(to.getHost()) && hub.getPort() == to.getPort());
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
        if (req.isForMainFrame()) a.showOffline();
    }
}

