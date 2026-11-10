# NovaPerf SDK 无反射调用第三方库；仅保留公开 API 与广播接收器，避免宿主混淆丢失控制面。
-keep public class com.novaperf.sdk.NovaPerf { public *; }
-keep public class com.novaperf.sdk.NovaControlReceiver { public *; }
-keep class com.novaperf.sdk.SessionWriter$Json { public *; }
