import java.io.*;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** Bounded, authenticated business-cache installation. External fencing is mandatory. */
public class NativeCertifyCacheRestoreAgent {
    record Frame(Map<String,Map<Object,Object>> values,Map<String,Map<Object,Long>> deadlines) {}
    static final Set<String> BUSINESS = Set.of("credentialOfferCache", "preAuthCodeCache", "vcissuance");
    static final byte[] AAD = "kdbt-certify-process-cache-v1".getBytes(java.nio.charset.StandardCharsets.UTF_8);

    static Frame decode(Path file, byte[] key, ClassLoader loader) throws Exception {
        byte[] sealed = Files.readAllBytes(file);
        if (sealed.length < 28 || sealed.length > 32 * 1024 * 1024 + 28) throw new SecurityException("Snapshot size bound");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, sealed, 0, 12));
        cipher.updateAAD(AAD);
        Map<String,Map<Object,Object>> caches = new TreeMap<>();
        Map<String,Map<Object,Long>> deadlines=new TreeMap<>();
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(cipher.doFinal(sealed, 12, sealed.length - 12)))) {
            String version=in.readUTF();
            if (!Set.of("KDBT-CERTIFY-CACHE-V1","KDBT-CERTIFY-CACHE-V2").contains(version)) throw new SecurityException("Snapshot version mismatch");
            int count = in.readInt(), total = 0;
            if (count < 0 || count > 1000) throw new SecurityException("Cache count bound");
            for (int i = 0; i < count; i++) {
                String name = in.readUTF(); int entries = in.readInt();
                if (!name.matches("[A-Za-z0-9_.:-]{1,128}") || entries < 0 || entries > 100000 || (total += entries) > 100000 || caches.containsKey(name))
                    throw new SecurityException("Invalid cache framing");
                Map<Object,Object> values = new LinkedHashMap<>();
                Map<Object,Long> expiry=new LinkedHashMap<>();
                for (int j = 0; j < entries; j++) {
                    Object k = object(in, loader), v = object(in, loader);
                    if (values.containsKey(k)) throw new SecurityException("Duplicate cache key");
                    values.put(k,v);
                    long deadline=version.endsWith("V2")?in.readLong():-1;
                    if(version.endsWith("V2") && (deadline<0 || deadline>32503680000000L))throw new SecurityException("Invalid absolute cache expiry");
                    expiry.put(k,deadline);
                }
                caches.put(name,values);deadlines.put(name,expiry);
            }
            if (in.read() != -1) throw new SecurityException("Trailing snapshot data");
        }
        return new Frame(caches,deadlines);
    }
    static void prune(Map<Object,Object> values,Map<Object,Long> expiry) {
        long now=System.currentTimeMillis();
        values.keySet().removeIf(key -> expiry.get(key)>0 && expiry.get(key)<=now);
    }

    static Object object(DataInputStream in, ClassLoader loader) throws Exception {
        int size = in.readInt();
        if (size <= 0 || size > 1024 * 1024) throw new SecurityException("Record size bound");
        byte[] bytes = in.readNBytes(size);
        if (bytes.length != size) throw new EOFException();
        try (ObjectInputStream stream = new ObjectInputStream(new ByteArrayInputStream(bytes)) {
            protected Class<?> resolveClass(ObjectStreamClass description) throws IOException, ClassNotFoundException {
                return Class.forName(description.getName(), false, loader);
            }
            protected Class<?> resolveProxyClass(String[] interfaces) throws IOException { throw new InvalidClassException("Proxy classes forbidden"); }
        }) {
            stream.setObjectInputFilter(info -> {
                if (info.depth() > 40 || info.references() > 100000 || info.arrayLength() > 1000000 || info.streamBytes() > 1024 * 1024)
                    return ObjectInputFilter.Status.REJECTED;
                Class<?> type = info.serialClass();
                if (type == null) return ObjectInputFilter.Status.UNDECIDED;
                while (type.isArray()) type = type.getComponentType();
                String name = type.getName();
                return type.isPrimitive() || name.startsWith("java.lang.") || name.startsWith("java.util.") || name.startsWith("java.math.") ||
                    name.startsWith("io.mosip.certify.core.dto.") ? ObjectInputFilter.Status.ALLOWED : ObjectInputFilter.Status.REJECTED;
            });
            Object value = stream.readObject();
            if (stream.read() != -1) throw new SecurityException("Trailing object data");
            return value;
        }
    }

    static List<String> fingerprint(Map<?,?> map) throws Exception {
        List<String> values = new ArrayList<>();
        for (Map.Entry<?,?> entry : map.entrySet()) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (ObjectOutputStream out = new ObjectOutputStream(bytes)) { out.writeObject(entry.getKey()); out.writeObject(entry.getValue()); }
            values.add(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes.toByteArray())));
        }
        Collections.sort(values); return values;
    }

    @SuppressWarnings("unchecked")
    public static void agentmain(String argument, Instrumentation instrumentation) throws Exception {
        Path directory = Path.of(argument).toRealPath();
        if (!directory.toString().startsWith("/tmp/kdbt-private-cache-") || !Files.isDirectory(directory)) throw new SecurityException("Private recovery directory required");
        byte[] key = Files.readAllBytes(directory.resolve("snapshot.key"));
        if (key.length != 32) throw new SecurityException("AES-256 key required");
        Class<?> application = null;
        for (Class<?> type : instrumentation.getAllLoadedClasses())
            if (type.getName().equals("org.springframework.boot.SpringApplication")) application = type;
        if (application == null) throw new IllegalStateException("Retained application unavailable");
        ClassLoader loader = application.getClassLoader();
        Frame expectedFrame=decode(directory.resolve("expected.bin"), key, loader),desiredFrame=decode(directory.resolve("desired.bin"), key, loader);
        Map<String,Map<Object,Object>> expected=expectedFrame.values(),desired=desiredFrame.values();
        boolean allCaches = Files.exists(directory.resolve("restore-all-caches"));
        Set<String> selected = allCaches ? Set.copyOf(desired.keySet()) : BUSINESS;
        if (allCaches) {
            if (!expected.keySet().equals(selected) || !selected.containsAll(BUSINESS) || selected.size() > 64)
                throw new SecurityException("Complete bounded cache inventory required");
        } else if (!desired.keySet().equals(BUSINESS) || !expected.keySet().containsAll(BUSINESS)) {
            throw new SecurityException("Complete business cache projection required");
        }
        Object hook = null;
        for (Field field : application.getDeclaredFields())
            if (Modifier.isStatic(field.getModifiers()) && field.getType().getName().endsWith("SpringApplicationShutdownHook")) {
                field.setAccessible(true); hook = field.get(null);
            }
        if (hook == null) throw new IllegalStateException("Retained contexts unavailable");
        Class<?> managerClass = Class.forName("org.springframework.cache.CacheManager", false, loader);
        Class<?> cacheClass = Class.forName("org.springframework.cache.Cache", false, loader);
        Set<Object> managers = Collections.newSetFromMap(new IdentityHashMap<>());
        for (Field field : hook.getClass().getDeclaredFields()) {
            if (!Collection.class.isAssignableFrom(field.getType())) continue;
            field.setAccessible(true);
            for (Object context : new ArrayList<>((Collection<?>) field.get(hook))) {
                try { managers.addAll(((Map<?,?>)context.getClass().getMethod("getBeansOfType", Class.class).invoke(context,managerClass)).values()); }
                catch (NoSuchMethodException ignored) { }
            }
        }
        if (managers.size() != 1) throw new IllegalStateException("Exactly one retained cache manager required");
        Object manager = managers.iterator().next();
        if (allCaches && !new HashSet<>((Collection<String>) managerClass.getMethod("getCacheNames").invoke(manager)).equals(selected))
            throw new SecurityException("Live cache inventory differs");
        Map<String,Map<Object,Object>> live = new TreeMap<>(), before = new TreeMap<>();
        Map<String,Map<Object,Long>> beforeExpiry=new TreeMap<>();
        Map<String,Object> cacheBeans=new TreeMap<>();
        for (String name : selected) {
            Object cache = managerClass.getMethod("getCache", String.class).invoke(manager,name);
            Object storage = cacheClass.getMethod("getNativeCache").invoke(cache);
            if (!(storage instanceof Map<?,?>)) throw new IllegalStateException("Map cache required");
            Map<Object,Object> map = (Map<Object,Object>)storage;
            prune(expected.get(name),expectedFrame.deadlines().get(name));
            prune(desired.get(name),desiredFrame.deadlines().get(name));
            NativeCertifyCacheDeadline.validate(map);
            for(Object entry:desired.get(name).keySet()) {
                long deadline=desiredFrame.deadlines().get(name).get(entry);
                if(deadline<0)throw new SecurityException("Absolute cache expiry unavailable in old frame");
                if(deadline>System.currentTimeMillis()+366L*86400000L)throw new SecurityException("Cache expiry exceeds recovery bound");
            }
            if (!fingerprint(map).equals(fingerprint(expected.get(name)))) throw new SecurityException("Cache changed after export; installation refused");
            live.put(name,map);cacheBeans.put(name,cache);before.put(name,new LinkedHashMap<>(map));
            Map<Object,Long> expiry=new LinkedHashMap<>();
            for(Object entry:before.get(name).keySet())expiry.put(entry,NativeCertifyCacheDeadline.capture(map,entry));
            beforeExpiry.put(name,expiry);
        }
        try {
            for (String name : selected) {
                Map<Object,Object> map=NativeCertifyCacheDeadline.wrap(manager,name,cacheBeans.get(name),live.get(name));
                live.put(name,map);map.clear();
                for(Object entry:desired.get(name).keySet())NativeCertifyCacheDeadline.restore(map,entry,desired.get(name).get(entry),desiredFrame.deadlines().get(name).get(entry));
            }
            for (String name : selected) {
                prune(desired.get(name),desiredFrame.deadlines().get(name));
                if (!fingerprint(live.get(name)).equals(fingerprint(desired.get(name)))) throw new IllegalStateException("Installed cache verification failed");
            }
        } catch (Exception failure) {
            for (String name : selected) {
                Map<Object,Object> map=live.get(name);map.clear();
                before.get(name).keySet().removeIf(entry -> beforeExpiry.get(name).get(entry)<0);
                map=NativeCertifyCacheDeadline.wrap(manager,name,cacheBeans.get(name),map);live.put(name,map);
                for(Object entry:before.get(name).keySet())NativeCertifyCacheDeadline.restore(map,entry,before.get(name).get(entry),beforeExpiry.get(name).get(entry));
            }
            throw failure;
        }
        Files.writeString(directory.resolve("restored.json"), "{\"installed\":true,\"cache_namespaces\":" + selected.size() + ",\"all_caches\":" + allCaches + ",\"external_fencing_required\":true}",StandardOpenOption.CREATE_NEW);
    }
}
