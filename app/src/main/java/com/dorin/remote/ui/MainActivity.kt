package com.dorin.remote.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import android.widget.Toast
import com.dorin.remote.RemoteViewModel

class MainActivity : ComponentActivity() {
    private val vm: RemoteViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            UniTheme {
                val ctx = LocalContext.current
                LaunchedEffect(Unit) {
                    vm.messages.collect { Toast.makeText(ctx, it, Toast.LENGTH_SHORT).show() }
                }
                Surface(modifier = Modifier.fillMaxSize(), color = Bg) {
                    Box(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
                        val showSetup by vm.showSetup.collectAsState()
                        if (showSetup) SetupScreen(vm) else RemoteScreen(vm)
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        vm.reconnect()
    }
}
