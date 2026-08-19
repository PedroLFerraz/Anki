# Retrofit / OkHttp
-dontwarn okhttp3.**
-dontwarn retrofit2.**
-keepattributes Signature, InnerClasses, EnclosingMethod
-keepattributes RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations

# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.pedrolopes.ankigen.data.model.** {
    *** Companion;
}
-keepclasseswithmembers class com.pedrolopes.ankigen.data.model.** {
    kotlinx.serialization.KSerializer serializer(...);
}
