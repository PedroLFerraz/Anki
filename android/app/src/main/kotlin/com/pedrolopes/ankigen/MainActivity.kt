package com.pedrolopes.ankigen

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Style
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.pedrolopes.ankigen.ui.cards.CardsScreen
import com.pedrolopes.ankigen.ui.generate.GenerateScreen
import com.pedrolopes.ankigen.ui.settings.SettingsScreen
import com.pedrolopes.ankigen.ui.theme.AnkiGenTheme
import com.pedrolopes.ankigen.ui.theme.Cyan
import com.pedrolopes.ankigen.ui.theme.Ink
import com.pedrolopes.ankigen.ui.theme.Paper
import com.pedrolopes.ankigen.ui.theme.SourceSerif4
import com.pedrolopes.ankigen.ui.theme.ink
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Broadsheet is a paper system: dark icons on a light ground.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.light(Paper.value.toInt(), Paper.value.toInt()),
            navigationBarStyle = SystemBarStyle.light(Paper.value.toInt(), Paper.value.toInt()),
        )
        setContent {
            AnkiGenTheme { AnkiGenApp() }
        }
    }
}

private enum class Screen(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    Generate("generate", "Generate", Icons.Default.AutoAwesome),
    Cards("cards", "Cards", Icons.Default.Style),
    Settings("settings", "Settings", Icons.Default.Tune),
}

@Composable
private fun AnkiGenApp() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination

    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val showMessage: (String) -> Unit = { msg ->
        scope.launch { snackbarHostState.showSnackbar(msg) }
    }

    Scaffold(
        containerColor = Paper,
        // No top app bar: each screen sets its own masthead kicker, the way
        // the canvas does.
        bottomBar = {
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(Paper)
                    .navigationBarsPadding()
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 4.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                Screen.entries.forEach { screen ->
                    val selected =
                        currentRoute?.hierarchy?.any { it.route == screen.route } == true
                    TabItem(
                        screen = screen,
                        selected = selected,
                        modifier = Modifier.weight(1f),
                        onClick = {
                            navController.navigate(screen.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                    )
                }
            }
        },
        snackbarHost = {
            SnackbarHost(snackbarHostState) { data ->
                Snackbar(
                    containerColor = Ink,
                    contentColor = Paper,
                    shape = MaterialTheme.shapes.extraSmall,
                ) {
                    Text(data.visuals.message, style = MaterialTheme.typography.bodyMedium)
                }
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Generate.route,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            composable(Screen.Generate.route) { GenerateScreen(onMessage = showMessage) }
            composable(Screen.Cards.route) { CardsScreen(onMessage = showMessage) }
            composable(Screen.Settings.route) { SettingsScreen() }
        }
    }
}

@Composable
private fun TabItem(
    screen: Screen,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val tint = if (selected) Cyan else ink(0.5f)
    val interaction = remember { MutableInteractionSource() }
    Column(
        modifier
            .clickable(
                interactionSource = interaction,
                indication = null,
                onClick = onClick,
            )
            .padding(vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(screen.icon, contentDescription = screen.label, tint = tint, modifier = Modifier.size(22.dp))
        Spacer(Modifier.height(2.dp))
        Text(
            screen.label,
            style = TextStyle(
                fontFamily = SourceSerif4,
                fontSize = 11.5.sp,
                letterSpacing = 0.23.sp,
            ),
            color = tint,
        )
    }
}
