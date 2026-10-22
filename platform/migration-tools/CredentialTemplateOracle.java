import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Retained formatter runs only as an offline migration-test reference. */
public class CredentialTemplateOracle {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        DataInputStream input = new DataInputStream(System.in);
        String template = NativeCredentialTemplate.string(input);
        Map<String,Object> values = (Map<String,Object>) NativeCredentialTemplate.value(input, 0);
        Class<?> configType = Class.forName("io.mosip.certify.entity.CredentialConfig");
        Object config = configType.getConstructor().newInstance();
        configType.getMethod("setVcTemplate", String.class).invoke(config,
            Base64.getEncoder().encodeToString(template.getBytes(StandardCharsets.UTF_8)));
        Class<?> repository = Class.forName("io.mosip.certify.repository.CredentialConfigRepository");
        Object proxy = Proxy.newProxyInstance(repository.getClassLoader(), new Class<?>[]{repository},
            (object, method, parameters) -> method.getName().startsWith("findBy") ? Optional.of(config) : null);
        Class<?> formatter = Class.forName("io.mosip.certify.vcformatters.VelocityTemplatingEngineImpl");
        Object instance = formatter.getConstructor().newInstance();
        Field field = formatter.getDeclaredField("credentialConfigRepository");
        field.setAccessible(true); field.set(instance, proxy);
        formatter.getMethod("initialize").invoke(instance);
        Object result = formatter.getMethod("format", Map.class).invoke(instance, values);
        System.out.write(result.toString().getBytes(StandardCharsets.UTF_8));
    }
}
