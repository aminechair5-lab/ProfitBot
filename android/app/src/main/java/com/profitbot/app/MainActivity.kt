package com.profitbot.app

import android.os.Bundle
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
import androidx.compose.ui.unit.dp
import java.util.Locale

data class Opportunity(
    val name: String, val category: String, val demand: Int, val competition: Int,
    val supplierCost: Double, val shipping: Double, val sellPrice: Double, val source: String
) {
    val estimatedProfit get() = sellPrice - supplierCost - shipping - sellPrice * 0.12
    val margin get() = if (sellPrice > 0) estimatedProfit / sellPrice * 100 else 0.0
    val score get() = (demand * 0.45 + (100 - competition) * 0.35 + margin.coerceIn(0.0, 100.0) * 0.20).toInt()
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); setContent { ProfitBotApp() } }
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

    Scaffold(
        topBar = { TopAppBar(title = { Text("ProfitBot • Owner Console") }, actions = { Icon(Icons.Default.VerifiedUser, contentDescription = "مالك") }) },
        bottomBar = {
            NavigationBar {
                listOf("الرئيسية", "فرص المنتجات", "الموافقات", "قنوات التسويق", "الحسابات").forEach { p ->
                    NavigationBarItem(selected = page == p, onClick = { page = p },
                        icon = { Icon(when(p) {
                            "فرص المنتجات" -> Icons.Default.TravelExplore
                            "الموافقات" -> Icons.Default.GppGood
                            "قنوات التسويق" -> Icons.Default.Campaign
                            "الحسابات" -> Icons.Default.AccountBalanceWallet
                            else -> Icons.Default.Dashboard
                        }, contentDescription = p) }, label = { Text(p) })
                }
            }
        }
    ) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad).padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when(page) {
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
                    item { Text("Product Radar", style = MaterialTheme.typography.headlineSmall) }
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
                    item { Text("المرحلة التالية: استبدال العينات بمصادر موثقة عبر APIs رسمية وربطها بتاريخ التحقق.") }
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
                                Button(onClick = { /* Prototype only: approval is recorded locally, no action is executed */ approvals = approvals - a }) { Text("موافقة تجريبية") }
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
