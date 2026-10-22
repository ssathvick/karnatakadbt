import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/** Absolute cache expiry translation for the exact retained Guava cache. */
public class NativeCertifyCacheDeadline {
    static boolean recovered(Map<?,?> map) throws Exception {
        if(map.getClass().getClassLoader()!=NativeCertifyCacheDeadline.class.getClassLoader() ||
           !map.getClass().getName().matches(("NativeCertifyCache"+"Deadline(?:[0-9a-f]{12})?\\$RecoveredMap")))return false;
        if(map.getClass().getField("PROTOCOL").getInt(null)!=1)throw new SecurityException("Unknown recovery map protocol");
        return true;
    }
    static final Map<Object,long[]> CLOCKS=new IdentityHashMap<>();
    static Object field(Object object,String name) throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }
    static boolean guava(Map<?,?> map) {
        if (map.getClass().getName().equals("com.google.common.cache.LocalCache")) return true;
        if (map instanceof ConcurrentHashMap<?,?>) return false;
        throw new IllegalStateException("Cache implementation needs an expiry adapter");
    }
    static long ticker(Map<?,?> map) throws Exception {
        Object ticker=field(map,"ticker");
        Class<?> type=Class.forName("com.google.common.base.Ticker",false,map.getClass().getClassLoader());
        return (Long)type.getMethod("read").invoke(ticker);
    }
    static long[] clock(Map<?,?> map) throws Exception {
        Object ticker=field(map,"ticker");
        synchronized(CLOCKS) {
            long[] value=CLOCKS.get(ticker);
            if(value==null) {value=new long[]{ticker(map),System.currentTimeMillis()};CLOCKS.put(ticker,value);}
            long mapped=value[1]+(ticker(map)-value[0])/1_000_000L;
            if(Math.abs(System.currentTimeMillis()-mapped)>2000)throw new IllegalStateException("Cache recovery clock changed");
            return value;
        }
    }
    static Object entry(Map<?,?> map,Object key) throws Exception {
        Method method=map.getClass().getDeclaredMethod("getEntry",Object.class);method.setAccessible(true);return method.invoke(map,key);
    }
    static Object invokeEntry(Object entry,String name,Class<?>[] types,Object... args) throws Exception {
        Method method=entry.getClass().getMethod(name,types);method.setAccessible(true);return method.invoke(entry,args);
    }
    static long duration(Map<?,?> map,String name) throws Exception {
        long value=(Long)field(map,name);if(value<0)throw new IllegalStateException("Invalid cache expiry policy");return value;
    }
    public static boolean expiring(Map<?,?> map) throws Exception {
        return guava(map) && (duration(map,"expireAfterWriteNanos")>0 || duration(map,"expireAfterAccessNanos")>0);
    }
    /** Zero denotes an unbounded map; minus one denotes an expired entry. */
    public static long capture(Map<?,?> map,Object key) throws Exception {
        if(recovered(map))return (Long)map.getClass().getMethod("captureDeadline",Object.class).invoke(map,key);
        if (!guava(map)) return map.containsKey(key)?0:-1;
        Object entry=entry(map,key);if(entry==null)return -1;
        long[] clock=clock(map);long nano=ticker(map),expiry=Long.MAX_VALUE;
        for(String kind:new String[]{"Write","Access"}) {
            long duration=duration(map,"expireAfter"+kind+"Nanos");
            if(duration>0) {
                long at=(Long)invokeEntry(entry,"get"+kind+"Time",new Class<?>[]{});
                expiry=Math.min(expiry,Math.addExact(at,duration));
            }
        }
        if(expiry==Long.MAX_VALUE)return 0;
        if(expiry-nano<1_000_000)return -1;
        return Math.addExact(clock[1],Math.floorDiv(Math.subtractExact(expiry,clock[0]),1_000_000));
    }
    public static void validate(Map<?,?> map) throws Exception {
        if(!recovered(map) && guava(map)) {
            for(String property:List.of("keyEquivalence","valueEquivalence"))
                if(!field(map,property).getClass().getName().equals("com.google.common.base.Equivalence$Equals"))
                    throw new SecurityException("Strong equality cache entries required");
        }
    }
    @SuppressWarnings("unchecked")
    public static Map<Object,Object> wrap(Object manager,String name,Object cache,Map<Object,Object> map) throws Exception {
        validate(map);if(recovered(map))return map;
        String type=manager.getClass().getName();
        if(!Set.of("org.springframework.cache.support.SimpleCacheManager","org.springframework.cache.concurrent.ConcurrentMapCacheManager").contains(type))
            throw new SecurityException("Unrecognized retained cache manager");
        if(!cache.getClass().getName().equals("org.springframework.cache.concurrent.ConcurrentMapCache") ||
            (Boolean)cache.getClass().getMethod("isStoreByValue").invoke(cache))throw new SecurityException("Unsupported retained cache storage");
        RecoveredMap wrapped=new RecoveredMap((ConcurrentMap<Object,Object>)map);
        Object replacement=cache.getClass().getConstructor(String.class,ConcurrentMap.class,boolean.class)
            .newInstance(name,wrapped,cache.getClass().getMethod("isAllowNullValues").invoke(cache));
        Field registry=null;
        for(Class<?> current=manager.getClass();current!=null;current=current.getSuperclass()) {
            try {registry=current.getDeclaredField("cacheMap");break;}catch(NoSuchFieldException ignored){}
        }
        if(registry==null)throw new IllegalStateException("Retained cache registry unavailable");
        registry.setAccessible(true);
        if(!((ConcurrentMap<Object,Object>)registry.get(manager)).replace(name,cache,replacement))throw new SecurityException("Cache binding changed before installation");
        return wrapped;
    }
    public static void restore(Map<Object,Object> map,Object key,Object value,long deadline) throws Exception {
        if(!recovered(map))throw new SecurityException("Verified recovery map required");
        map.getClass().getMethod("restoreEntry",Object.class,Object.class,long.class).invoke(map,key,value,deadline);
    }
    /** Restored entries retain absolute expiry; ordinary writes keep Guava's policy. */
    public static final class RecoveredMap extends AbstractMap<Object,Object> implements ConcurrentMap<Object,Object> {
        public static final int PROTOCOL=1;
        record Restored(Object value,long deadline) {}
        final ConcurrentMap<Object,Object> delegate;
        final Map<Object,Restored> restored=new HashMap<>();
        RecoveredMap(ConcurrentMap<Object,Object> delegate) {this.delegate=delegate;}
        Restored active(Object key) {
            Restored entry=restored.get(key);
            if(entry!=null && entry.deadline()>0 && entry.deadline()<=System.currentTimeMillis()) {restored.remove(key);return null;}
            return entry;
        }
        public synchronized long captureDeadline(Object key) throws Exception {
            Restored entry=active(key);return entry==null?NativeCertifyCacheDeadline.capture(delegate,key):entry.deadline();
        }
        public synchronized void restoreEntry(Object key,Object value,long deadline) {
            Objects.requireNonNull(key);Objects.requireNonNull(value);
            if(deadline<0 || deadline>System.currentTimeMillis()+366L*86400000L)throw new SecurityException("Bounded absolute cache expiry required");
            restored.remove(key);delegate.remove(key);
            if(deadline==0 || deadline>System.currentTimeMillis())restored.put(key,new Restored(value,deadline));
        }
        public synchronized Object get(Object key) {Objects.requireNonNull(key);Restored entry=active(key);return entry==null?delegate.get(key):entry.value();}
        public synchronized boolean containsKey(Object key) {return get(key)!=null;}
        public synchronized Object put(Object key,Object value) {
            Objects.requireNonNull(key);Objects.requireNonNull(value);Object old=get(key);restored.remove(key);delegate.put(key,value);return old;
        }
        public synchronized Object remove(Object key) {Object old=get(key);restored.remove(key);delegate.remove(key);return old;}
        public synchronized void clear() {restored.clear();delegate.clear();}
        public synchronized Object putIfAbsent(Object key,Object value) {Objects.requireNonNull(value);Object old=get(key);if(old==null)put(key,value);return old;}
        public synchronized boolean remove(Object key,Object value) {Object old=get(key);if(old==null || !old.equals(value))return false;remove(key);return true;}
        public synchronized Object replace(Object key,Object value) {Objects.requireNonNull(value);Object old=get(key);if(old!=null)put(key,value);return old;}
        public synchronized boolean replace(Object key,Object old,Object value) {Objects.requireNonNull(value);Object current=get(key);if(current==null || !current.equals(old))return false;put(key,value);return true;}
        synchronized Map<Object,Object> snapshot() {
            Map<Object,Object> values=new LinkedHashMap<>(delegate);
            for(Object key:new ArrayList<>(restored.keySet())) {Restored entry=active(key);if(entry!=null)values.put(key,entry.value());}
            return values;
        }
        public int size() {return snapshot().size();}
        public Set<Map.Entry<Object,Object>> entrySet() {
            return new AbstractSet<>() {
                public int size() {return RecoveredMap.this.size();}
                public void clear() {RecoveredMap.this.clear();}
                public boolean remove(Object value) {return value instanceof Map.Entry<?,?> entry && RecoveredMap.this.remove(entry.getKey(),entry.getValue());}
                public Iterator<Map.Entry<Object,Object>> iterator() {
                    Iterator<Map.Entry<Object,Object>> source=snapshot().entrySet().iterator();
                    return new Iterator<>() {
                        Map.Entry<Object,Object> current;
                        public boolean hasNext() {return source.hasNext();}
                        public Map.Entry<Object,Object> next() {
                            current=source.next();Object key=current.getKey();
                            return new SimpleEntry<>(current) {public Object setValue(Object value) {Object old=RecoveredMap.this.put(key,value);super.setValue(value);return old;}};
                        }
                        public void remove() {if(current==null)throw new IllegalStateException();RecoveredMap.this.remove(current.getKey(),current.getValue());current=null;}
                    };
                }
            };
        }
    }
}
