import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.*;
import org.springframework.cache.concurrent.ConcurrentMapCacheManager;

/** Original components run offline against owned fixtures, never production caches. */
public class CertifyRecoveryOracle {
    static final ObjectMapper JSON = new ObjectMapper();
    static Object create(String name) throws Exception { return Class.forName(name).getConstructor().newInstance(); }
    static Object dto(String name) throws Exception { return create("io.mosip.certify.core.dto." + name); }
    static Object call(Object target, String name, Object... args) throws Exception {
        for (Method method : target.getClass().getMethods()) {
            if (!method.getName().equals(name) || method.getParameterCount() != args.length) continue;
            Class<?>[] types = method.getParameterTypes(); boolean matches = true;
            for (int index = 0; index < args.length; index++) {
                if (args[index] != null && !types[index].isInstance(args[index]) &&
                    !(types[index] == boolean.class && args[index] instanceof Boolean) &&
                    !(types[index] == int.class && args[index] instanceof Integer) &&
                    !(types[index] == long.class && args[index] instanceof Long)) matches = false;
            }
            if (matches) return method.invoke(target, args);
        }
        throw new NoSuchMethodException(name);
    }
    static String serialized(Object value) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ObjectOutputStream out = new ObjectOutputStream(bytes)) { out.writeObject(value); }
        return Base64.getEncoder().encodeToString(bytes.toByteArray());
    }
    static Object read(Path path) throws Exception {
        try (ObjectInputStream in = new ObjectInputStream(Files.newInputStream(path))) {
            in.setObjectInputFilter(ObjectInputFilter.Config.createFilter(
                "maxdepth=32;maxrefs=20000;maxbytes=1048576;io.mosip.certify.core.dto.*;java.lang.*;java.util.Map$Entry;java.util.HashMap;java.util.ArrayList;!*"));
            return in.readObject();
        }
    }
    static void field(Object object, String name, Object value) throws Exception {
        Field field = object.getClass().getDeclaredField(name);
        field.setAccessible(true); field.set(object, value);
    }
    static void require(boolean value) { if (!value) throw new IllegalStateException("Retained state mismatch"); }
    public static void main(String[] args) throws Exception {
        if (args[0].startsWith("qr-")) {
            Class<?> constants = Class.forName("io.mosip.pixelpass.shared.ConstantsKt");
            Object keys = constants.getMethod("getCLAIM_169_KEY_MAPPER").invoke(null);
            Object values = constants.getMethod("getCLAIM_169_VALUE_MAPPER").invoke(null);
            if (args[0].equals("qr-mappings")) {
                System.out.println(JSON.writeValueAsString(Map.of("keys", keys, "values", values))); return;
            }
            Object pixel = create("io.mosip.pixelpass.PixelPass");
            if (args[0].equals("qr-map")) {
                Object data = Class.forName("org.json.JSONObject").getConstructor(String.class)
                    .newInstance(Files.readString(Path.of(args[1])));
                System.out.println(call(pixel, "getMappedData", data, keys, values, true)); return;
            }
            if (args[0].equals("qr-decode")) {
                System.out.println(call(pixel, "decode", Files.readString(Path.of(args[1])))); return;
            }
        }
        if (args[0].equals("svg-digest")) {
            System.out.println(Class.forName("io.mosip.certify.services.CredentialUtils")
                .getMethod("getDigestMultibase", String.class).invoke(null, Files.readString(Path.of(args[1]))));
            return;
        }
        if (args[0].equals("templates")) {
            Map<String,String> values = new LinkedHashMap<>();
            values.put("transaction", serialized(dto("PreAuthTransaction")));
            values.put("code", serialized(dto("PreAuthCodeData")));
            values.put("offer", serialized(dto("CredentialOfferResponse")));
            values.put("grant", serialized(dto("Grant")));
            values.put("preauth_grant", serialized(dto("Grant$PreAuthorizedCodeGrantType")));
            values.put("tx_code", serialized(dto("TxCode")));
            System.out.println(JSON.writeValueAsString(values)); return;
        }
        Path folder = Path.of(args[1]);
        JsonNode expected = JSON.readTree(folder.resolve("expected.json").toFile());
        Object code = read(folder.resolve("code.bin"));
        Object offer = read(folder.resolve("offer.bin"));
        Object transaction = read(folder.resolve("transaction.bin"));
        require(JSON.valueToTree(call(code, "getClaims")).equals(expected.get("claims")));
        require(call(code, "getTxnCode").equals(expected.get("tx_code").asText()));
        require(((Number)call(code, "getExpiresAt")).longValue() == expected.get("code_expires_at").asLong() * 1000);
        require(call(code, "getCredentialConfigurationId").equals(expected.get("configuration").asText()));
        Object grant = call(call(offer, "getGrants"), "getPreAuthorizedCode");
        require(call(grant, "getPreAuthorizedCode").equals(expected.get("code").asText()));
        require(((Number)call(call(grant, "getTxCode"), "getLength")).intValue() == expected.get("tx_code").asText().length());
        require(call(transaction, "getCNonce").equals(expected.get("nonce").asText()));
        require(((Number)call(transaction, "getCNonceIssuedEpoch")).longValue() + ((Number)call(transaction, "getCNonceExpireSeconds")).intValue() == expected.get("session_expires_at").asLong());
        require(JSON.valueToTree(call(transaction, "getClaims")).equals(expected.get("claims")));
        ConcurrentMapCacheManager manager = new ConcurrentMapCacheManager("vcissuance", "preAuthCodeCache", "credentialOfferCache");
        Object cache = create("io.mosip.certify.services.VCICacheService"); field(cache, "cacheManager", manager);
        call(cache, "setPreAuthCodeData", expected.get("code").asText(), code);
        require(call(cache, "getPreAuthCodeData", expected.get("code").asText()).equals(code));
        require((Boolean)call(cache, "claimPreAuthCode", expected.get("code").asText()));
        require(!(Boolean)call(cache, "claimPreAuthCode", expected.get("code").asText()));
        manager.getCache("vcissuance").put(expected.get("access_token_hash").asText(), transaction);
        Object parsed = dto("ParsedAccessToken"); call(parsed, "setAccessTokenHash", expected.get("access_token_hash").asText());
        Object provider = create("io.mosip.certify.services.PreAuthIssuanceServiceImpl");
        field(provider, "vciCacheService", cache); field(provider, "parsedAccessToken", parsed);
        require(JSON.readTree(call(provider, "fetchData", new HashMap<>()).toString()).equals(expected.get("claims")));
        call(transaction, "setCNonce", "retained-binary-rotated-owned-nonce");
        try (ObjectOutputStream out = new ObjectOutputStream(Files.newOutputStream(folder.resolve("original-rotated.bin")))) {
            out.writeObject(transaction);
        }
        System.out.println("ORIGINAL_COMPONENTS_ACCEPT_NATIVE_STATE_AND_ENFORCE_SINGLE_USE=true");
    }
}
