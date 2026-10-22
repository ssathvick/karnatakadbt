import java.io.*;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.SecureRandom;
import java.util.*;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** Read-only encrypted cache observation. No business classes or bytecode change. */
public class NativeCertifyCacheSnapshotAgent {
    record Captured(byte[] key,byte[] value,long deadline,String type) {}
    static final byte[] AAD = "kdbt-certify-process-cache-v1".getBytes(java.nio.charset.StandardCharsets.UTF_8);
    public static void agentmain(String argument, Instrumentation instrumentation) throws Exception {
        Path directory = Path.of(argument).toRealPath();
        if (!directory.toString().startsWith("/tmp/kdbt-private-cache-") || !Files.isDirectory(directory))
            throw new SecurityException("Private capture directory required");
        byte[] key = Files.readAllBytes(directory.resolve("snapshot.key"));
        if (key.length != 32) throw new SecurityException("AES-256 capture key required");
        Class<?> application = null;
        for (Class<?> type : instrumentation.getAllLoadedClasses())
            if (type.getName().equals("org.springframework.boot.SpringApplication")) application = type;
        if (application == null) throw new IllegalStateException("Retained Spring application not found");
        Object hook = null;
        for (Field field : application.getDeclaredFields())
            if (Modifier.isStatic(field.getModifiers()) && field.getType().getName().endsWith("SpringApplicationShutdownHook")) {
                field.setAccessible(true); hook = field.get(null);
            }
        if (hook == null) throw new IllegalStateException("Retained application context unavailable");
        Set<Object> managers = Collections.newSetFromMap(new IdentityHashMap<>());
        Class<?> cacheManager = Class.forName("org.springframework.cache.CacheManager", false, application.getClassLoader());
        for (Field field : hook.getClass().getDeclaredFields()) {
            if (!Collection.class.isAssignableFrom(field.getType())) continue;
            field.setAccessible(true); Object collection = field.get(hook);
            if (!(collection instanceof Collection<?>)) continue;
            for (Object context : new ArrayList<>((Collection<?>) collection)) {
                try {
                    Method beans = context.getClass().getMethod("getBeansOfType", Class.class);
                    managers.addAll(((Map<?, ?>) beans.invoke(context, cacheManager)).values());
                } catch (NoSuchMethodException irrelevant) { }
            }
        }
        if (managers.isEmpty()) throw new IllegalStateException("No observable retained cache manager");
        Class<?> cacheType = Class.forName("org.springframework.cache.Cache", false, application.getClassLoader());
        List<String> metadata = new ArrayList<>();
        ByteArrayOutputStream plain = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(plain)) {
            out.writeUTF("KDBT-CERTIFY-CACHE-V2");
            List<Map.Entry<String, Map<?, ?>>> caches = new ArrayList<>();
            for (Object manager : managers) {
                Collection<?> names = (Collection<?>) cacheManager.getMethod("getCacheNames").invoke(manager);
                for (Object value : new ArrayList<>(names)) {
                    String name = value.toString();
                    if (!name.matches("[A-Za-z0-9_.:-]{1,128}")) throw new SecurityException("Unsupported cache name");
                    Object cache = cacheManager.getMethod("getCache", String.class).invoke(manager, name);
                    Object storage = cacheType.getMethod("getNativeCache").invoke(cache);
                    if (!(storage instanceof Map<?, ?>)) throw new IllegalStateException("Non-map cache needs its own recovery adapter");
                    caches.add(Map.entry(name, (Map<?, ?>) storage));
                }
            }
            out.writeInt(caches.size());
            int total = 0;
            for (Map.Entry<String, Map<?, ?>> cache : caches) {
                List<Captured> records=new ArrayList<>();
                for (Map.Entry<?,?> entry:new LinkedHashMap<>(cache.getValue()).entrySet()) {
                    long deadline=NativeCertifyCacheDeadline.capture(cache.getValue(),entry.getKey());
                    if(deadline<0)continue;
                    records.add(new Captured(serialize(entry.getKey()),serialize(entry.getValue()),deadline,
                        entry.getValue()==null?"null":entry.getValue().getClass().getName()));
                }
                out.writeUTF(cache.getKey()); out.writeInt(records.size());
                Set<String> types = new TreeSet<>();
                for (Captured entry : records) {
                    if (++total > 100000) throw new SecurityException("Cache capture count exceeds bound");
                    byte[] encodedKey = entry.key(), encodedValue = entry.value();
                    out.writeInt(encodedKey.length); out.write(encodedKey); out.writeInt(encodedValue.length); out.write(encodedValue);
                    out.writeLong(entry.deadline());
                    if (plain.size() > 32 * 1024 * 1024) throw new SecurityException("Cache capture exceeds bounded size");
                    types.add(entry.type());
                }
                metadata.add("{\"name\":\"" + cache.getKey() + "\",\"entries\":" + records.size() +
                        ",\"value_classes\":[" + String.join(",", types.stream().map(s -> "\"" + s + "\"").toList()) + "]}");
            }
        }
        byte[] nonce = new byte[12]; new SecureRandom().nextBytes(nonce);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, nonce));
        cipher.updateAAD(AAD); byte[] sealed = cipher.doFinal(plain.toByteArray());
        try (OutputStream out = Files.newOutputStream(directory.resolve("snapshot.bin"), StandardOpenOption.CREATE_NEW)) {
            out.write(nonce); out.write(sealed);
        }
        Files.writeString(directory.resolve("metadata.json"), "{\"captured\":true,\"cache_managers\":" + managers.size() +
                ",\"caches\":[" + String.join(",", metadata) + "],\"fenced_snapshot\":false}", StandardOpenOption.CREATE_NEW);
    }
    static byte[] serialize(Object value) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ObjectOutputStream out = new ObjectOutputStream(bytes)) { out.writeObject(value); }
        if (bytes.size() > 1024 * 1024) throw new SecurityException("Cache record exceeds capture bound");
        return bytes.toByteArray();
    }
}
