package com.profitbot.app

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

private const val API_BASE_URL = "https://profitbot-484v.onrender.com"

data class Opportunity(
    val name: String, val category: String, val demand: Int, val competition: Int,
    val supplierCost: Double, val shipping: Double, val sellPrice: Double, val source: String
) {
    val estimatedProfit get() = sellPrice - supplierCost - shipping - sellPrice * 0.12
    val margin get() = if (sellPrice > 0) estimatedProfit / sellPrice * 100 else 0.0
    val score get() = (demand * 0.45 + (100 - competition) * 0.35 + margin.coerceIn(0.0, 100.0) * 0.20).toInt()
}

private data class ApiResponse(val code: Int, val body: String)

private fun apiGet(path: String, token: String): ApiResponse {
    val connection = (URL(API_BASE_URL + path).openConnection() as HttpURLConnection)
    try {
        connection.requestMethod = "GET"
        connection.connectTimeout = 15000
        connection.readTimeout = 20000
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Authorization", "Bearer $token")
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        return ApiResponse(code, body)
    } finally {
        connection.disconnect()
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ProfitBotApp() }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfitBotApp() {
    var page by remember { mutableStateOf("الرئيسية") }
    var opportunities by remember { mutableStateOf(listOf(
        Opportunity("منظم أدوات العناية للسفر", "Beauty & Travel", 78, 42, 4.5, 3.0, 18.0, "بيانات تجريبية"),
        Opportunity("حامل هاتف قابل للطي", "Tech Accessories", 72, 66, 3.2, 2.8, 14.0, "بيانات تجريبية"),
        Opportunity("منظم أدراج متعدد الاستخدام", "Home", 68, 48, 5.0, 4.0, 21.0, "بيانات تجريبية")
    )) }
    var approvals by remember { mutableStateOf(listOf("نشر صفحة منتج تجريبية", "طلب عينة من مورد — لم يُرسل")) }
    var selected by remember { mutableStateOf<Opportunity?>(null) }

    // The owner token remains in memory only; it is never written to disk or bundled in the APK.
    var ownerToken by remember { mutableStateOf("") }
    var connectionMessage by remember { mutableStateOf("غير متصل") }
    var isLoading by remember { mutableStateOf(false) }
    var summaryJson by remember { mutableStateOf<JSONObject?>(null) }
    var remoteProducts by remember { mutableStateOf(listOf<JSONObject>()) }
    var trendSignals by remember { mutableStateOf(listOf<JSONObject>()) }
    var trendMessage by remember { mutableStateOf("لم يتم جلب اتجاهات البحث بعد") }
    var trendsLoading by remember { mutableStateOf(false) }

    fun connectToCloud() {
        val token = ownerToken.trim()
        if (token.isEmpty() || isLoading) return
        isLoading = true
        connectionMessage = "جارٍ الاتصال بالخادم..."
        Thread {
            try {
                val summaryResponse = apiGet("/owner/summary", token)
                if (summaryResponse.code !in 200..299) {
                    Handler(Looper.getMainLooper()).post {
                        connectionMessage = when (summaryResponse.code) {
                            401 -> "رفض الخادم الرمز. تحقق من OWNER_API_TOKEN."
                            503 -> "رمز المالك غير مضبوط في إعدادات الخادم."
                            else -> "فشل الاتصال: HTTP ${summaryResponse.code} — ${summaryResponse.body.take(180)}"
                        }
                        isLoading = false
                        summaryJson = null
                        remoteProducts = emptyList()
                    }
                    return@Thread
                }
                val productsResponse = apiGet("/products", token)
                if (productsResponse.code !in 200..299) {
                    Handler(Looper.getMainLooper()).post {
                        connectionMessage = "تم التحقق من الرمز، لكن تعذر جلب المنتجات (HTTP ${productsResponse.code})."
                        summaryJson = JSONObject(summaryResponse.body)
                        isLoading = false
                    }
                    return@Thread
                }
                val summary = JSONObject(summaryResponse.body)
                val array = JSONArray(productsResponse.body)
                val products = (0 until array.length()).map { array.getJSONObject(it) }
                Handler(Looper.getMainLooper()).post {
                    summaryJson = summary
                    remoteProducts = products
                    connectionMessage = "متصل بالخادم بنجاح"
                    isLoading = false
                }
            } catch (e: Exception) {
                Handler(Looper.getMainLooper()).post {
                    connectionMessage = "تعذر الاتصال: ${e.message ?: "خطأ غير معروف"}"
                    isLoading = false
                    summaryJson = null
                    remoteProducts = emptyList()
                }
            }
        }.start()
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("ProfitBot • Owner Console") }, actions = { Icon(Icons.Default.VerifiedUser, contentDescription = "مالك") }) },
        bottomBar = {
            NavigationBar {
                listOf("الرئيسية", "فرص المنتجات", "الموافقات", "قنوات التسويق", "الحسابات", "اتصال الخادم").forEach { p ->
                    NavigationBarItem(selected = page == p, onClick = { page = p },
                        icon = { Icon(when(p) {
                            "فرص المنتجات" -> Icons.Default.TravelExplore
                            "الموافقات" -> Icons.Default.GppGood
                            "قنوات التسويق" -> Icons.Default.Campaign
                            "الحسابات" -> Icons.Default.AccountBalanceWallet
                            "اتصال الخادم" -> Icons.Default.Cloud
                            else -> Icons.Default.Dashboard
                        }, contentDescription = p) }, label = { Text(p) })
                }
            }
        }
    ) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad).padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when(page) {
                "اتصال الخادم" -> {
                    item { Text("الاتصال بـ ProfitBot Cloud", style = MaterialTheme.typography.headlineSmall) }
                    item { Text("أدخل رمز المالك الذي حفظته في Render. يستخدم التطبيق الرمز في الذاكرة أثناء التشغيل فقط ولا يحفظه على الهاتف.") }
                    item {
                        OutlinedTextField(
                            value = ownerToken,
                            onValueChange = { ownerToken = it; summaryJson = null; remoteProducts = emptyList(); connectionMessage = "لم يتم الاتصال بعد" },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("رمز المالك OWNER_API_TOKEN") },
                            visualTransformation = PasswordVisualTransformation(),
                            singleLine = true
                        )
                    }
                    item {
                        Button(onClick = { connectToCloud() }, enabled = ownerToken.isNotBlank() && !isLoading, modifier = Modifier.fillMaxWidth()) {
                            if (isLoading) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            else Icon(Icons.Default.CloudSync, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text(if (isLoading) "جارٍ الاتصال..." else "اتصال وجلب البيانات")
                        }
                    }
                    item {
                        Card {
                            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text("حالة الاتصال", style = MaterialTheme.typography.titleMedium)
                                Text(connectionMessage, color = if (summaryJson != null) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                                Text("الخادم: $API_BASE_URL", style = MaterialTheme.typography.bodySmall)
                                Text("الاتصال يستخدم HTTPS. لا توجد عمليات شراء أو دفع أو نشر من هذه الشاشة.", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    summaryJson?.let { summary ->
                        item { Text("ملخص الحساب من الخادم", style = MaterialTheme.typography.titleLarge) }
                        item { Stat("المنتجات المسجلة", summary.optInt("product_candidates").toString(), "بيانات قاعدة بيانات الخادم") }
                        item { Stat("المنتجات المؤهلة", summary.optInt("eligible_candidates").toString(), "حسب قواعد التقييم الحالية") }
                        item { Stat("موافقات تنتظر القرار", summary.optInt("pending_approvals").toString(), "لا يتم تنفيذ العمليات تلقائياً") }
                        item { Stat("هدف الربح الشهري", "$" + summary.optInt("target_monthly_profit_usd"), "هدف وليس ربحاً محققاً") }
                        item { Text(summary.optString("monthly_net_profit_note"), style = MaterialTheme.typography.bodySmall) }
                        item { Text("منتجات الخادم (${remoteProducts.size})", style = MaterialTheme.typography.titleLarge) }
                        if (remoteProducts.isEmpty()) item { Text("لا توجد منتجات محفوظة في قاعدة البيانات بعد.") }
                        items(remoteProducts) { product ->
                            Card {
                                Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    Text(product.optString("name"), style = MaterialTheme.typography.titleMedium)
                                    Text("${product.optString("category")} • ${product.optString("target_market")}", style = MaterialTheme.typography.bodySmall)
                                    Text("التقييم: ${product.optDouble("score").toInt()}/100 • مؤهل: ${if (product.optBoolean("eligible")) "نعم" else "لا"}")
                                    Text("الربح الصافي التقديري: ${money(product.optDouble("estimated_net_profit"))} • الهامش: ${product.optDouble("estimated_margin_pct").toInt()}%")
                                }
                            }
                        }
                    }
                    item {
                        OutlinedButton(onClick = { ownerToken = ""; summaryJson = null; remoteProducts = emptyList(); connectionMessage = "تم مسح الرمز من ذاكرة التطبيق" }, modifier = Modifier.fillMaxWidth()) {
                            Text("مسح رمز المالك من الذاكرة")
                        }
                    }
                }
                "الرئيسية" -> {
                    item { Text("مركز قيادة المالك", style = MaterialTheme.typography.headlineSmall) }
                    item { Stat("هدف الدخل الشهري", "$100", "هدف تخطيطي وليس ضماناً") }
                    item { Stat("فرص أولية", opportunities.size.toString(), "عينات توضيحية وليست بيانات سوق حية") }
                    item { Stat("عمليات تنتظر موافقتك", approvals.size.toString(), "لا دفع ولا نشر تلقائي") }
                    item {
                        Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("نمط التشغيل: استقلالية عالية", style = MaterialTheme.typography.titleMedium)
                            Text("البحث والتحليل وتجهيز المسودات آلياً. النشر والشراء والدفع والتحويل تبقى خلف موافقة المالك.")
                            Text("الأسواق: عالمية — لا توجد دولة بيع مفعلة قبل التحقق من الشحن والدفع والضرائب.")
                        } }
                    }
                    item { Text("قاعدة القرار: لا نختار المنتج بسبب الترند وحده؛ يجب أن يجتاز هامش الربح والشحن والمخاطر.") }
                }
                "فرص المنتجات" -> {
                    item { Text("رادار إشارات السوق", style = MaterialTheme.typography.headlineSmall) }
                    item { Text("Google Trends يعرض اهتمام البحث، وليس بيانات مبيعات أو منتجات مؤكدة.") }
                    item {
                        Button(onClick = {
                            val token = ownerToken.trim()
                            if (token.isEmpty()) {
                                trendMessage = "افتح اتصال الخادم وأدخل رمز المالك أولاً."
                            } else if (!trendsLoading) {
                                trendsLoading = true
                                trendMessage = "جارٍ جلب إشارات البحث..."
                                Thread {
                                    try {
                                        val response = apiGet("/signals/trends?geo=US", token)
                                        val rows = if (response.code in 200..299) {
                                            val arr = JSONObject(response.body).optJSONArray("items") ?: JSONArray()
                                            (0 until arr.length()).map { arr.getJSONObject(it) }
                                        } else emptyList()
                                        Handler(Looper.getMainLooper()).post {
                                            trendSignals = rows
                                            trendMessage = if (response.code in 200..299)
                                                "تم جلب ${rows.size} إشارة بحث."
                                            else "تعذر الجلب: HTTP ${response.code}"
                                            trendsLoading = false
                                        }
                                    } catch (e: Exception) {
                                        Handler(Looper.getMainLooper()).post {
                                            trendMessage = "خطأ: ${e.message ?: "تعذر الاتصال"}"
                                            trendsLoading = false
                                        }
                                    }
                                }.start()
                            }
                        }, enabled = !trendsLoading, modifier = Modifier.fillMaxWidth()) {
                            if (trendsLoading) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            else Icon(Icons.Default.CloudDownload, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text(if (trendsLoading) "جارٍ الجلب..." else "جلب اتجاهات البحث")
                        }
                    }
                    item { Text(trendMessage, style = MaterialTheme.typography.bodySmall) }
                    items(trendSignals) { signal ->
                        Card {
                            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                                Text(signal.optString("title"), style = MaterialTheme.typography.titleMedium)
                                Text("حركة بحث تقريبية: ${signal.optString("approx_traffic", "غير محددة")}")
                                Text("المصدر: Google Trends • ليست مبيعات مؤكدة")
                                Text(signal.optString("url"), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    item { Text("يلزم التحقق من المورد والتكلفة والشحن والمنافسة قبل اعتماد أي فكرة.") }
                    item { Text("عينات توضيحية قديمة", style = MaterialTheme.typography.titleMedium) }
                    item { Text("ترتيب تجريبي: الطلب 45% • انخفاض المنافسة 35% • هامش الربح 20%") }
                    items(opportunities.sortedByDescending { it.score }) { op ->
                        Card(onClick = { selected = op }) {
                            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                                    Text(op.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                    AssistChip(onClick = { selected = op }, label = { Text("Score ${op.score}") })
                                }
                                Text("${op.category} • المصدر: ${op.source}", style = MaterialTheme.typography.bodySmall)
                                Text("ربح تقديري: ${money(op.estimatedProfit)} لكل قطعة • هامش: ${op.margin.toInt()}%")
                                Text("الطلب ${op.demand}/100 • المنافسة ${op.competition}/100")
                                Text("اضغط للتفاصيل وحساب الربح")
                            }
                        }
                    }
                    item { Text("هذه فرص تجريبية محلية؛ المنتجات الحقيقية تظهر في تبويب اتصال الخادم بعد إضافتها إلى قاعدة البيانات.") }
                }
                "الموافقات" -> {
                    item { Text("صندوق موافقات المالك", style = MaterialTheme.typography.headlineSmall) }
                    item { Text("كل طلب شراء أو دفع أو نشر يظهر هنا قبل التنفيذ.") }
                    items(approvals) { a ->
                        Card { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(a, style = MaterialTheme.typography.titleMedium)
                            Text("الحالة: مسودة / غير منفّذ")
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(onClick = { approvals = approvals - a }) { Text("رفض / حذف") }
                                Button(onClick = { approvals = approvals - a }) { Text("موافقة تجريبية") }
                            }
                        } }
                    }
                    item { Text("الموافقة هنا محلية للعرض فقط؛ لا ترسل أمراً إلى PayPal أو المورد أو Blogger.") }
                }
                "قنوات التسويق" -> {
                    item { Text("خطة التسويق العضوي", style = MaterialTheme.typography.headlineSmall) }
                    val channels = listOf(
                        "Blogger / SEO" to "مقالات حل المشكلات ومراجعات شفافة وروابط المنتج.",
                        "Reddit" to "رصد الأسئلة والمشكلات والمشاركة المفيدة دون نشر إعلاني مزعج.",
                        "Pinterest" to "أفكار مرئية وروابط صفحات مفيدة مع احترام قواعد المنصة.",
                        "YouTube Shorts / TikTok" to "مقاطع أصلية قصيرة؛ النشر بعد موافقتك.",
                        "Google Trends" to "مقارنة الاهتمام الموسمي والبلدان والعبارات."
                    )
                    items(channels) { (n,d) -> Card { Column(Modifier.padding(14.dp)) { Text(n, style = MaterialTheme.typography.titleMedium); Text(d) } } }
                    item { Text("لا يوجد نشر حي أو جدولة فعلية في هذه النسخة.") }
                }
                else -> {
                    item { Text("الحسابات والاتصالات", style = MaterialTheme.typography.headlineSmall) }
                    val accounts = listOf(
                        "Blogger" to "OAuth مطلوب لإدارة مقالات مدونتك.",
                        "PayPal Personal" to "تحقق من أهلية استقبال المدفوعات التجارية وCheckout قبل الدمج.",
                        "RedotPay Card" to "وسيلة إنفاق محتملة للموردين؛ ليست وسيلة Checkout للزبائن.",
                        "Binance" to "منفصل عن دورة مدفوعات المتجر في الإصدار الأول.",
                        "Reddit" to "API وسياسات المجتمعات مطلوبة.",
                        "المتجر المستقل" to "نختار المنصة بعد مقارنة التكلفة والدول المدعومة."
                    )
                    items(accounts) { (n,d) -> Card { Column(Modifier.padding(14.dp)) { Text(n, style = MaterialTheme.typography.titleMedium); Text(d); Text("غير متصل", color = MaterialTheme.colorScheme.secondary) } } }
                    item { Text("لا تضع كلمات المرور أو مفاتيح API في التطبيق أو المحادثة. سنستخدم OAuth وخادماً آمناً.") }
                }
            }
        }
    }

    selected?.let { op ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(op.name) },
            text = { Text("تكلفة المنتج: ${money(op.supplierCost)}\nالشحن: ${money(op.shipping)}\nسعر البيع المفترض: ${money(op.sellPrice)}\nاحتياطي رسوم افتراضي 12%: ${money(op.sellPrice * .12)}\nالربح التقديري: ${money(op.estimatedProfit)}\nهامش الربح: ${op.margin.toInt()}%\n\nهذه بيانات تجريبية. لا تعتمدها قبل التحقق من المورد والرسوم والضرائب والمرتجعات.") },
            confirmButton = { TextButton(onClick = { selected = null }) { Text("إغلاق") } })
    }
}

@Composable
fun Stat(title: String, value: String, hint: String) {
    Card { Column(Modifier.fillMaxWidth().padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(value, style = MaterialTheme.typography.headlineMedium)
        Text(hint, style = MaterialTheme.typography.bodySmall)
    } }
}

fun money(v: Double) = String.format(Locale.US, "$%.2f", v)
